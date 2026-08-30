import ipaddress
import os
import re
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field, HttpUrl, model_validator

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

SERVICE_VERSION = "1.10.0"
PROTOCOL_VERSION = f"capi2.claim_verify/{SERVICE_VERSION}"
COMMERCE_PROTOCOL = "capi2.verifiable_commerce/1.0"
BRAND_PROMISE = "Verifiable commerce for autonomous agents."

PAY_TO = os.getenv("CAPI2_PAY_TO", "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a")
NETWORK = os.getenv("CAPI2_X402_NETWORK", "eip155:8453")
FACILITATOR_URL = os.getenv("CAPI2_X402_FACILITATOR", "https://facilitator.payai.network")
PRICE = os.getenv("CAPI2_CLAIM_VERIFY_PRICE", "$0.01")
PUBLIC_ORIGIN = os.getenv("CAPI2_CLAIM_VERIFY_ORIGIN", "https://capi2-claim-verify.onrender.com").rstrip("/")
AGENT402_REGISTER = os.getenv("CAPI2_AGENT402_REGISTER", "true").lower() == "true"
MAX_SOURCE_BYTES = int(os.getenv("CAPI2_MAX_SOURCE_BYTES", "2000000"))
MAX_REDIRECTS = 3
MAX_SOURCES = 3
MARKET_RADAR_CACHE_TTL = 300
_MARKET_RADAR_CACHE: dict[str, tuple[float, dict]] = {}
_MARKET_RADAR_LOCK = threading.Lock()

BUYER_TAGS = [
    "verifiable agent commerce", "agent preflight", "delivery verification",
    "commerce receipts", "claim verification", "vendor risk", "procurement",
]
BUYER_QUERIES = [
    "verify a vendor claim against public evidence",
    "fact check an AI vendor or SaaS claim",
    "procurement due diligence evidence",
    "vendor risk evidence check",
    "RFP or security questionnaire claim verification",
]
BEST_FOR = [
    "Checking whether one or more supplied public pages contain support for a precise vendor claim",
    "Extracting short evidence snippets for procurement, RFP, security, privacy, and SaaS review workflows",
    "Getting a conservative supported, contradicted, or uncertain result in structured JSON",
]
NOT_FOR = [
    "Independent certification, legal advice, or a full vendor audit",
    "Discovering sources across the open web; the buyer must supply the URLs",
    "Automated regulated or high-impact decisions without qualified human review",
]
PAID_CANARY = {
    "verified": True,
    "amount_usdc": "0.01",
    "network": "eip155:8453",
    "marketplace": "PayAPI Market",
    "transaction": "0x4e94a877189eda0e0eb8950a1a1fde68cef7b1dee85edc2bc1e31834617c38fb",
    "scope": "payment and HTTP 200 production canary; not an organic customer sale",
}

MATCH_STOPWORDS = {
    "about", "against", "claim", "claims", "public", "source", "states", "state",
    "that", "their", "there", "these", "this", "vendor", "with",
}
NEGATORS = {"not", "no", "never", "without", "cannot", "cant", "lacks", "lacking"}

CLAIM_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor_url": {
            "type": "string",
            "format": "uri",
            "description": "Public source URL containing evidence relevant to the claim.",
        },
        "source_urls": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_SOURCES,
            "uniqueItems": True,
            "items": {"type": "string", "format": "uri"},
            "description": (
                "Optional list of up to three public evidence URLs. These are checked together; "
                "vendor_url remains supported for backward compatibility."
            ),
        },
        "claim": {
            "type": "string",
            "minLength": 3,
            "maxLength": 1200,
            "description": "Vendor, product, compliance, security, or commercial claim to verify.",
        },
        "vendor_name": {"type": "string", "maxLength": 200},
        "claim_id": {"type": "string", "maxLength": 200},
        "request_type": {"type": "string", "maxLength": 120},
        "verification_type": {"type": "string", "maxLength": 120},
    },
    "anyOf": [{"required": ["vendor_url", "claim"]}, {"required": ["source_urls", "claim"]}],
    "additionalProperties": True,
}

CLAIM_OUTPUT_EXAMPLE = {
    "protocol": PROTOCOL_VERSION,
    "vendor_url": "https://example.com/security",
    "claim": "Vendor states that customer data is encrypted at rest.",
    "verification_status": "supported",
    "verification_result": "supported",
    "verdict": "SUPPORTED_BY_SUPPLIED_SOURCE",
    "confidence": 0.88,
    "evidence_summary": "Customer data is encrypted at rest.",
    "evidence_source_urls": ["https://example.com/security"],
    "evidence": [{
        "text": "Customer data is encrypted at rest.",
        "score": 0.9,
        "source_url": "https://example.com/security"
    }],
    "caveats": ["Checks only the supplied public URL."],
    "request_id": "cv_018f5f8f0c2b4f7a",
    "checked_at": "2026-08-26T15:00:00Z",
    "sources_checked": 1,
    "source_results": [{
        "requested_url": "https://example.com/security",
        "final_url": "https://example.com/security",
        "status": "checked"
    }],
}

CLAIM_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "protocol": {"type": "string"},
        "claim_id": {"type": ["string", "null"]},
        "vendor_name": {"type": ["string", "null"]},
        "vendor_url": {"type": "string"},
        "claim": {"type": "string"},
        "verification_status": {"type": "string", "enum": ["supported", "contradicted", "uncertain"]},
        "verification_result": {"type": "string", "enum": ["supported", "contradicted", "uncertain"]},
        "verdict": {"type": "string"},
        "confidence": {"type": "number"},
        "evidence_summary": {"type": "string"},
        "evidence_source_urls": {"type": "array", "items": {"type": "string"}},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "score": {"type": "number"},
                    "source_url": {"type": ["string", "null"]},
                },
                "required": ["text", "score", "source_url"],
            },
        },
        "caveats": {"type": "array", "items": {"type": "string"}},
        "request_id": {"type": "string"},
        "checked_at": {"type": "string", "format": "date-time"},
        "sources_checked": {"type": "integer", "minimum": 1, "maximum": MAX_SOURCES},
        "source_results": {"type": "array", "items": {"type": "object"}},
    },
    "required": [
        "protocol", "vendor_url", "claim", "verification_status", "verification_result",
        "verdict", "confidence", "evidence_summary", "evidence_source_urls", "evidence", "caveats",
        "request_id", "checked_at", "sources_checked", "source_results",
    ],
}

DRY_RUN_FIXTURES = {
    "supporting_evidence_with_unrelated_negation": {
        "claim": "The API supports single sign-on (SSO).",
        "evidence_text": (
            "There are no setup fees for enterprise accounts, and the API supports "
            "single sign-on (SSO) for enterprise customers."
        ),
        "expected_verification_status": "supported",
        "purpose": (
            "Regression for the 1.3.2 verdict-inversion class: unrelated negation in a "
            "supporting sentence must not flip a supported claim to contradicted."
        ),
    },
    "direct_relevant_contradiction": {
        "claim": "The API supports single sign-on (SSO).",
        "evidence_text": "The API does not support single sign-on (SSO).",
        "expected_verification_status": "contradicted",
        "purpose": "Control case proving that relevant negation still produces a contradiction.",
    },
}


def _bazaar_claim_extension() -> dict:
    return {
        "bazaar": {
            "info": {
                "input": {
                    "type": "http",
                    "method": "POST",
                    "bodyType": "json",
                    "body": {
                        "vendor_url": "https://example.com/security",
                        "claim": "Vendor states that customer data is encrypted at rest.",
                        "vendor_name": "Example Vendor",
                        "request_type": "vendor_due_diligence",
                    },
                },
                "output": {"type": "json", "example": CLAIM_OUTPUT_EXAMPLE},
            },
            "schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "input": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "const": "http"},
                            "method": {"type": "string", "enum": ["POST", "PUT", "PATCH"]},
                            "bodyType": {"type": "string", "enum": ["json", "form-data", "text"]},
                            "body": CLAIM_INPUT_SCHEMA,
                        },
                        "required": ["type", "method", "bodyType", "body"],
                        "additionalProperties": False,
                    },
                    "output": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "example": CLAIM_OUTPUT_SCHEMA,
                        },
                        "required": ["type"],
                    },
                },
                "required": ["input"],
            },
        }
    }


app = FastAPI(
    title="capi2 Claim Verify",
    version=SERVICE_VERSION,
    description=(
        "Verifiable commerce for autonomous agents: preflight decisions, delivery checks "
        "and evidence-backed commerce receipts, with x402 settlement on Base USDC."
    ),
)

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
server = x402ResourceServer(facilitator)
server.register(NETWORK, ExactEvmServerScheme())

routes = {
    "POST /v1/claim-verify": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=PAY_TO, price=PRICE, network=NETWORK)],
        resource=f"{PUBLIC_ORIGIN}/v1/claim-verify",
        mime_type="application/json",
        description=(
            "Check a public vendor, product, security, compliance, procurement or commercial "
            "claim against up to three buyer-supplied public URLs and return machine-readable evidence, verdict "
            "and confidence for autonomous-agent workflows."
        ),
        service_name="capi2 Claim Verify",
        tags=BUYER_TAGS,
        extensions=_bazaar_claim_extension(),
    )
}
app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


class ClaimVerifyRequest(BaseModel):
    vendor_url: Optional[HttpUrl] = None
    source_urls: Optional[List[HttpUrl]] = Field(default=None, min_length=1, max_length=MAX_SOURCES)
    claim: Optional[str] = Field(default=None, min_length=3, max_length=1200)
    context_url: Optional[HttpUrl] = None
    claim_to_verify: Optional[str] = Field(default=None, min_length=3, max_length=1200)
    claim_text: Optional[str] = Field(default=None, min_length=3, max_length=1200)
    vendor_name: Optional[str] = Field(default=None, max_length=200)
    claim_id: Optional[str] = Field(default=None, max_length=200)
    request_type: Optional[str] = Field(default=None, max_length=120)
    verification_type: Optional[str] = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def require_resolvable_input(self):
        if self.vendor_url is None and self.context_url is None and not self.source_urls:
            raise ValueError("vendor_url, context_url, or source_urls is required")
        if not (self.claim or self.claim_to_verify or self.claim_text):
            raise ValueError("claim, claim_to_verify, or claim_text is required")
        return self

    def resolved_url(self) -> str:
        return self.resolved_urls()[0]

    def resolved_urls(self) -> list[str]:
        urls = [str(url) for url in (self.source_urls or [])]
        legacy_url = self.vendor_url or self.context_url
        if legacy_url is not None:
            urls.insert(0, str(legacy_url))
        return list(dict.fromkeys(urls))[:MAX_SOURCES]

    def resolved_claim(self) -> str:
        return str(self.claim or self.claim_to_verify or self.claim_text)


class EvidenceSnippet(BaseModel):
    text: str
    score: float
    source_url: Optional[str] = None


class ClaimVerifyResponse(BaseModel):
    protocol: str = PROTOCOL_VERSION
    claim_id: Optional[str] = None
    vendor_name: Optional[str] = None
    vendor_url: str
    claim: str
    verification_status: str
    verification_result: str
    verdict: str
    confidence: float
    evidence_summary: str
    evidence_source_urls: List[str]
    evidence: List[EvidenceSnippet]
    caveats: List[str]
    request_id: str
    checked_at: str
    sources_checked: int
    source_results: List[dict]


class DryRunRequest(BaseModel):
    fixture_id: Optional[str] = None
    claim: Optional[str] = Field(default=None, min_length=3, max_length=1200)
    evidence_text: Optional[str] = Field(default=None, min_length=3, max_length=4000)

    @model_validator(mode="after")
    def require_fixture_or_pair(self):
        if self.fixture_id:
            if self.fixture_id not in DRY_RUN_FIXTURES:
                raise ValueError(f"unknown fixture_id; choose one of: {', '.join(DRY_RUN_FIXTURES)}")
            return self
        if not self.claim or not self.evidence_text:
            raise ValueError("provide fixture_id, or both claim and evidence_text")
        return self


def _word_list(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _tokens(text: str) -> set[str]:
    return {
        token for token in _word_list(text)
        if len(token) >= 4 and token not in MATCH_STOPWORDS and token not in NEGATORS
    }


def _sentence_chunks(text: str) -> List[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [re.sub(r"\s+", " ", c).strip() for c in chunks if len(c.strip()) >= 25]


def _relevant_negation(text: str, target_terms: set[str]) -> bool:
    if not target_terms:
        return False
    words = _word_list(text)
    for i, word in enumerate(words):
        if word not in target_terms:
            continue
        window = words[max(0, i - 3):i]
        if any(token in NEGATORS for token in window):
            return True
    normalized = " ".join(words)
    for term in target_terms:
        if re.search(rf"\b(?:fails|failed|unable)\s+to\s+(?:\w+\s+){{0,1}}{re.escape(term)}\b", normalized):
            return True
    return False


def _rank_evidence(claim: str, page_text: str) -> list[tuple[float, str]]:
    claim_tokens = _tokens(claim)
    if not claim_tokens:
        raise HTTPException(status_code=422, detail="claim_has_insufficient_terms")
    ranked: list[tuple[float, str]] = []
    for chunk in _sentence_chunks(page_text):
        chunk_tokens = _tokens(chunk)
        if not chunk_tokens:
            continue
        overlap = len(claim_tokens & chunk_tokens)
        score = overlap / max(len(claim_tokens), 1)
        if overlap:
            ranked.append((score, chunk[:420]))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def _classify_claim(claim: str, evidence_text: str) -> dict:
    ranked = _rank_evidence(claim, evidence_text)
    top = ranked[:3]
    best = top[0][0] if top else 0.0
    best_text = top[0][1] if top else ""
    claim_terms = _tokens(claim)
    best_terms = _tokens(best_text) if best_text else set()
    shared_terms = claim_terms & best_terms
    claim_negated = _relevant_negation(claim, claim_terms)
    evidence_negated = _relevant_negation(best_text, shared_terms) if best_text else False

    if best >= 0.60 and claim_negated == evidence_negated:
        verification_status = "supported"
        verdict = "SUPPORTED_BY_SUPPLIED_SOURCE"
    elif best >= 0.55 and claim_negated != evidence_negated:
        verification_status = "contradicted"
        verdict = "CONTRADICTED_BY_SUPPLIED_SOURCE"
    else:
        verification_status = "uncertain"
        verdict = "NOT_CONFIRMED_OR_AMBIGUOUS"

    if verification_status == "contradicted":
        confidence = min(0.90, round(0.30 + best * 0.58, 3))
    else:
        confidence = min(0.95, round(0.25 + best * 0.70, 3))

    evidence = [{"text": text, "score": round(score, 3)} for score, text in top]
    return {
        "verification_status": verification_status,
        "verification_result": verification_status,
        "verdict": verdict,
        "confidence": confidence,
        "evidence_summary": best_text or "No sufficiently overlapping public statement was found on the supplied source.",
        "evidence": evidence,
        "debug": {
            "best_overlap": round(best, 3),
            "claim_negated_near_relevant_terms": claim_negated,
            "evidence_negated_near_relevant_terms": evidence_negated,
            "shared_terms": sorted(shared_terms),
        },
    }


def _validate_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="source_url_must_be_public_http_or_https")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".local"):
        raise HTTPException(status_code=422, detail="source_url_private_host_blocked")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        resolved = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(status_code=422, detail="source_dns_resolution_failed") from exc
    if not resolved:
        raise HTTPException(status_code=422, detail="source_dns_resolution_failed")
    for entry in resolved:
        ip = ipaddress.ip_address(entry[4][0])
        if not ip.is_global:
            raise HTTPException(status_code=422, detail="source_url_private_or_reserved_ip_blocked")


def _fetch_public_source(url: str) -> tuple[str, str]:
    current = url
    headers = {"User-Agent": f"capi2-claim-verify/{SERVICE_VERSION} (+public-evidence-check)"}
    for _ in range(MAX_REDIRECTS + 1):
        _validate_public_http_url(current)
        try:
            response = requests.get(
                current, timeout=(4, 12), allow_redirects=False, stream=True, headers=headers,
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=422, detail=f"source_fetch_failed:{exc.__class__.__name__}") from exc
        if 300 <= response.status_code < 400:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise HTTPException(status_code=422, detail="source_redirect_without_location")
            current = urljoin(current, location)
            continue
        if response.status_code >= 400:
            status = response.status_code
            response.close()
            raise HTTPException(status_code=422, detail=f"source_http_status:{status}")
        declared_length = response.headers.get("content-length")
        if declared_length and declared_length.isdigit() and int(declared_length) > MAX_SOURCE_BYTES:
            response.close()
            raise HTTPException(status_code=422, detail="source_too_large")
        encoding = response.encoding or "utf-8"
        data = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                data.extend(chunk)
                if len(data) > MAX_SOURCE_BYTES:
                    raise HTTPException(status_code=422, detail="source_too_large")
        finally:
            response.close()
        return current, bytes(data).decode(encoding, errors="replace")
    raise HTTPException(status_code=422, detail="too_many_source_redirects")


def _extract_page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def _price_usd() -> float:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", PRICE)
    return float(match.group(1)) if match else 0.01


def _lifecycle() -> list[dict]:
    return [
        {
            "step": "discover",
            "method": "GET",
            "paths": ["/", "/.well-known/x402", "/.well-known/agent.json", "/openapi.json", "/llms.txt", "/robots.txt"],
            "payment_required": False,
        },
        {"step": "quote", "method": "GET", "path": "/v1/quote", "payment_required": False},
        {
            "step": "sandbox",
            "method": "POST",
            "path": "/v1/claim-verify/dry-run",
            "payment_required": False,
            "behavior": "Free text-only regression/sandbox classifier. It does not fetch external URLs.",
        },
        {
            "step": "pay",
            "method": "POST",
            "path": "/v1/claim-verify",
            "behavior": "An unpaid request returns HTTP 402 with x402 payment requirements; the buyer pays and retries with proof.",
        },
        {
            "step": "execute",
            "method": "POST",
            "path": "/v1/claim-verify",
            "behavior": "After x402 verification/settlement, capi2 fetches the supplied public URL and evaluates evidence.",
        },
        {"step": "result", "mode": "inline", "success_status": 200, "content_type": "application/json"},
    ]


def _quote() -> dict:
    return {
        "protocol": "capi2.quote/1.2",
        "service": "claim_verify",
        "service_name": "capi2 Claim Verify",
        "description": "Check one precise claim against up to three buyer-supplied public source URLs and return evidence snippets plus a conservative verdict.",
        "best_for": BEST_FOR,
        "not_for": NOT_FOR,
        "price": PRICE,
        "asset": "USDC",
        "network": NETWORK,
        "payment_protocol": "x402",
        "pay_to": PAY_TO,
        "tags": BUYER_TAGS,
        "buyer_queries": BUYER_QUERIES,
        "execute": {
            "method": "POST",
            "url": f"{PUBLIC_ORIGIN}/v1/claim-verify",
            "path": "/v1/claim-verify",
            "content_type": "application/json",
            "input_schema": CLAIM_INPUT_SCHEMA,
            "example_body": {
                "vendor_url": "https://example.com/security",
                "claim": "Vendor states that customer data is encrypted at rest.",
            },
        },
        "sandbox": {
            "method": "POST",
            "url": f"{PUBLIC_ORIGIN}/v1/claim-verify/dry-run",
            "payment_required": False,
            "network_fetch": False,
            "fixture_id": "supporting_evidence_with_unrelated_negation",
        },
        "result": {"mode": "inline", "success_status": 200, "content_type": "application/json", "example": CLAIM_OUTPUT_EXAMPLE},
        "marketplace": {
            "standard_fee_bps": 1000,
            "provider_share_bps": 9000,
            "note": "The 10/90 split applies to routed third-party marketplace jobs; this first-party service settles to the configured capi2 pay_to address.",
        },
        "production_proof": PAID_CANARY,
    }


def _x402_manifest() -> dict:
    return {
        "name": "capi2 Claim Verify",
        "service_name": "capi2 Claim Verify",
        "version": SERVICE_VERSION,
        "description": "Paid supplied-source evidence matching for vendor claims, AI/SaaS due diligence, procurement, RFP and security workflows.",
        "homepage": PUBLIC_ORIGIN,
        "protocol": "x402",
        "network": NETWORK,
        "asset": "USDC",
        "payTo": PAY_TO,
        "tags": BUYER_TAGS,
        "buyer_queries": BUYER_QUERIES,
        "best_for": BEST_FOR,
        "not_for": NOT_FOR,
        "production_proof": PAID_CANARY,
        "resources": [
            {
                "name": "capi2 Claim Verify",
                "resource": f"{PUBLIC_ORIGIN}/v1/claim-verify",
                "endpoint": "POST /v1/claim-verify",
                "method": "POST",
                "price_usd": _price_usd(),
                "tags": BUYER_TAGS,
                "summary": "Check one precise claim against up to three buyer-supplied public URLs and return evidence snippets plus a conservative verdict.",
                "input_schema": CLAIM_INPUT_SCHEMA,
                "example_request": {
                    "vendor_url": "https://example.com/security",
                    "claim": "Vendor states that customer data is encrypted at rest.",
                },
                "output_example": CLAIM_OUTPUT_EXAMPLE,
                "discovery_extension": "bazaar",
            }
        ],
        "free_endpoints": [
            "/", "/buy", "/health", "/robots.txt", "/llms.txt", "/.well-known/x402",
            "/.well-known/x402-service.json",
            "/.well-known/agent.json", "/openapi.json", "/v1/quote", "/v1/examples",
            "/v1/claim-verify/schema", "/v1/claim-verify/dry-run",
        ],
    }


def _manifest() -> dict:
    return {
        "name": "capi2 Claim Verify",
        "protocol": PROTOCOL_VERSION,
        "positioning": BRAND_PROMISE,
        "commerce_protocol": COMMERCE_PROTOCOL,
        "description": "Evidence and receipt infrastructure for autonomous agents buying services and APIs.",
        "service_name": "capi2 Claim Verify",
        "tags": BUYER_TAGS,
        "buyer_queries": BUYER_QUERIES,
        "best_for": BEST_FOR,
        "not_for": NOT_FOR,
        "production_proof": PAID_CANARY,
        "discovery": {
            "x402": "/.well-known/x402", "agent": "/.well-known/agent.json",
            "x402_service": "/.well-known/x402-service.json",
            "openapi": "/openapi.json", "llms": "/llms.txt", "robots": "/robots.txt",
            "quote": "/v1/quote", "examples": "/v1/examples",
            "dry_run": "/v1/claim-verify/dry-run", "bazaar_extension": True,
        },
        "quote": {"method": "GET", "path": "/v1/quote"},
        "endpoint": {"method": "POST", "path": "/v1/claim-verify", "url": f"{PUBLIC_ORIGIN}/v1/claim-verify"},
        "sandbox": {
            "method": "POST", "path": "/v1/claim-verify/dry-run",
            "url": f"{PUBLIC_ORIGIN}/v1/claim-verify/dry-run",
            "payment_required": False, "network_fetch": False,
            "regression_fixture": "supporting_evidence_with_unrelated_negation",
        },
        "lifecycle": _lifecycle(),
        "payment": {"protocol": "x402", "network": NETWORK, "asset": "USDC", "price": PRICE, "payTo": PAY_TO},
        "input": {
            "canonical": {"source_urls": ["https://...", "https://..."], "claim": "..."},
            "schema": CLAIM_INPUT_SCHEMA,
            "aliases": [["context_url", "claim_to_verify"], ["vendor_url", "claim_text"]],
            "optional": ["vendor_url", "source_urls", "vendor_name", "claim_id", "request_type", "verification_type"],
        },
        "output": {
            "delivery": "inline_after_successful_payment_and_execution",
            "status_fields": ["verification_status", "verification_result"],
            "status_values": ["supported", "contradicted", "uncertain"],
            "evidence_fields": ["evidence_summary", "evidence_source_urls", "evidence"],
            "example": CLAIM_OUTPUT_EXAMPLE,
        },
    }


@app.get("/")
async def root():
    return {
        "name": "capi2 Claim Verify",
        "version": SERVICE_VERSION,
        "paid": True,
        "price": PRICE,
        "asset": "USDC",
        "network": NETWORK,
        "what_it_does": "Match one precise vendor or product claim against up to three buyer-supplied public URLs and return evidence snippets plus a conservative verdict.",
        "best_for": BEST_FOR,
        "not_for": NOT_FOR,
        "production_proof": PAID_CANARY,
        "discover": {
            "human_page": f"{PUBLIC_ORIGIN}/buy",
            "x402": f"{PUBLIC_ORIGIN}/.well-known/x402",
            "x402_service": f"{PUBLIC_ORIGIN}/.well-known/x402-service.json",
            "agent": f"{PUBLIC_ORIGIN}/.well-known/agent.json",
            "openapi": f"{PUBLIC_ORIGIN}/openapi.json",
            "llms": f"{PUBLIC_ORIGIN}/llms.txt",
            "quote": f"{PUBLIC_ORIGIN}/v1/quote",
            "dry_run": f"{PUBLIC_ORIGIN}/v1/claim-verify/dry-run",
            "x402_adoption_kit": f"{PUBLIC_ORIGIN}/v1/x402-adoption-kit",
            "verifiable_commerce": f"{PUBLIC_ORIGIN}/v1/verifiable-commerce",
            "free_x402_market_radar": f"{PUBLIC_ORIGIN}/v1/free-x402-market-radar",
        },
        "buy": {"method": "POST", "url": f"{PUBLIC_ORIGIN}/v1/claim-verify"},
    }


@app.get("/buy", response_class=HTMLResponse)
async def buyer_page():
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CAPI2 — Verifiable commerce for autonomous agents</title>
<meta name="description" content="Preflight agent purchases, verify delivery and retain machine-readable commerce receipts.">
<style>
body{margin:0;background:#081611;color:#f2f7f4;font:17px/1.55 system-ui,sans-serif}.w{max-width:1050px;margin:auto;padding:28px}nav{display:flex;justify-content:space-between;align-items:center;font-weight:800}.tag{color:#0b271b;background:#bdf45b;padding:6px 11px;border-radius:999px;font-size:13px}.hero{padding:90px 0 55px;max-width:900px}h1{font-size:clamp(48px,8vw,88px);line-height:.94;letter-spacing:-.055em;margin:0 0 24px}.hero p{font-size:21px;color:#b9cbc2;max-width:760px}.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:28px}.btn,.ghost{padding:13px 18px;border-radius:10px;text-decoration:none;font-weight:800}.btn{background:#bdf45b;color:#102117}.ghost{color:#eff8f3;border:1px solid #486258}.flow{color:#bdf45b;margin:18px 0 35px;font-weight:750}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}.card{background:#10251c;border:1px solid #294539;border-radius:16px;padding:22px}.card b{font-size:20px}.card p{color:#aabfb5}.foot{margin-top:58px;border-top:1px solid #294539;padding:24px 0;color:#8fa69b;font-size:14px}@media(max-width:760px){.grid{grid-template-columns:1fr}.hero{padding-top:55px}}
</style></head><body><main class="w"><nav><span>CAPI2</span><span class="tag">x402 · Base USDC · from $0.01</span></nav>
<section class="hero"><h1>Verifiable commerce for autonomous agents.</h1><p>AI agents can buy services and APIs. CAPI2 provides evidence of who authorized the purchase, what was ordered, what was delivered and how payment settled.</p><div class="flow">Request → authority → policy → payment → delivery → verification → receipt</div><div class="actions"><a class="btn" href="/v1/verifiable-commerce">Explore the product contract</a><a class="ghost" href="/docs">Open API docs</a><a class="ghost" href="/v1/claim-verify/dry-run">Free validation</a></div></section>
<section class="grid"><article class="card"><b>Agent Preflight</b><p>Check authority, policy and seller claims before an autonomous buyer signs payment.</p></article><article class="card"><b>Delivery Verify</b><p>Compare the delivered result with the agreed claim and retain cited evidence.</p></article><article class="card"><b>Commerce Receipt</b><p>Portable proof connecting request, decision, delivery, verification and settlement.</p></article></section>
<footer class="foot">CAPI2 provides an evidence layer—not certification or legal advice. High-impact decisions require authorized review.</footer></main></body></html>"""


@app.get("/legacy-buy", response_class=HTMLResponse, include_in_schema=False)
async def legacy_buyer_page():
    return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>capi2 Claim Verify — Evidence before trust</title><meta name="description" content="Verify vendor, security and procurement claims against public evidence. Agent-native x402 API from $0.01 USDC on Base."><link rel="canonical" href="https://capi2-claim-verify.onrender.com/buy"><link rel="icon" href="/favicon.ico"><meta property="og:type" content="website"><meta property="og:title" content="capi2 Claim Verify — Evidence before trust"><meta property="og:description" content="Evidence-backed vendor claim verification for humans and AI agents. Pay per request with x402 USDC on Base."><meta property="og:url" content="https://capi2-claim-verify.onrender.com/buy"><meta name="twitter:card" content="summary"><script type="application/ld+json">{"@context":"https://schema.org","@type":"SoftwareApplication","name":"capi2 Claim Verify","applicationCategory":"BusinessApplication","operatingSystem":"Web API","description":"Agent-native vendor, security and procurement claim verification against supplied public evidence.","offers":{"@type":"AggregateOffer","lowPrice":"0.01","highPrice":"0.04","priceCurrency":"USD"}}</script><style>body{margin:0;background:#f4f1e8;color:#15231d;font:16px/1.55 system-ui,sans-serif}.w{max-width:980px;margin:auto;padding:32px}nav{display:flex;justify-content:space-between;font-weight:800}.tag{background:#dff06a;padding:6px 11px;border-radius:999px;font-size:13px}.hero{padding:90px 0 55px;max-width:820px}h1{font-size:clamp(44px,8vw,82px);line-height:.94;letter-spacing:-.055em;margin:0 0 25px}p{color:#5c6b64;font-size:19px}.actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:28px}.btn{background:#176b4d;color:white;padding:13px 18px;border-radius:10px;text-decoration:none;font-weight:800}.ghost{color:inherit;border:1px solid #bcc6bf;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:750}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}.card{background:#fffdf7;border:1px solid #d9ddd6;border-radius:15px;padding:20px}.card b{font-size:18px}.sample{margin:55px 0;background:#14231d;color:#eaf4ee;border-radius:18px;padding:25px}.sample p{color:#bdd0c6}.sample code{white-space:pre-wrap}.proof{margin:32px 0;padding:18px;border-left:4px solid #176b4d;background:#e9efe9}.proof a{color:#176b4d;font-weight:800}.foot{border-top:1px solid #d9ddd6;padding:24px 0;color:#6b7771;font-size:14px}@media(max-width:720px){.grid{grid-template-columns:1fr}.hero{padding-top:55px}}</style></head><body><main class="w"><nav><span>capi2 Claim Verify</span><span class="tag">$0.01–$0.04 · x402 · Base USDC</span></nav><section class="hero"><h1>Evidence before trust.</h1><p>Check vendor, product, security and procurement claims against supplied public sources. Receive cited evidence, contradictory signals, confidence and explicit caveats as structured JSON.</p><div class="actions"><a class="btn" href="/v1/samples/hiddenlayer">Open a real public sample</a><a class="ghost" href="/docs#/default/claim_verify_dry_run_v1_claim_verify_dry_run_post">Try the free dry-run</a><a class="ghost" href="/v1/buyer-catalog">Agent buyer catalog</a></div></section><section class="grid"><article class="card"><b>Procurement</b><p>Check supplier statements before they enter a questionnaire or decision memo.</p></article><article class="card"><b>AI agents</b><p>Pay once and receive an inline result—no account or subscription.</p></article><article class="card"><b>Vendor Risk Pack</b><p>Verify two to five claims in one $0.04 x402 purchase.</p></article></section><aside class="proof">Five paid resources are registered on <a href="https://www.x402scan.com/server/056707f7-5c8e-4f15-8712-419fd959c994">x402scan</a> and routable through Agent402.</aside><section class="sample"><b>Paid request</b><p>POST /v1/claim-verify</p><code>{
  "vendor_url": "https://vendor.example/security",
  "claim": "Customer data is encrypted at rest"
}</code></section><footer class="foot">Public-source evidence aid. Not certification or legal advice; consequential decisions require independent review.</footer></main></body></html>"""


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#176b4d"/><path d="M17 33c0-10 7-17 17-17 6 0 11 2 14 7l-8 6c-2-3-4-4-7-4-5 0-8 3-8 8s3 8 8 8c3 0 6-1 8-4l8 6c-4 5-9 7-16 7-10 0-16-7-16-17z" fill="#dff06a"/></svg>"""
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    xml = f"""<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{PUBLIC_ORIGIN}/buy</loc></url><url><loc>{PUBLIC_ORIGIN}/v1/buyer-catalog</loc></url><url><loc>{PUBLIC_ORIGIN}/.well-known/x402</loc></url><url><loc>{PUBLIC_ORIGIN}/openapi.json</loc></url></urlset>"""
    return Response(content=xml, media_type="application/xml")


@app.get("/health")
async def health():
    fixture = DRY_RUN_FIXTURES["supporting_evidence_with_unrelated_negation"]
    regression = _classify_claim(fixture["claim"], fixture["evidence_text"])
    return {
        "ok": regression["verification_status"] == "supported",
        "service": "capi2-claim-verify",
        "version": SERVICE_VERSION,
        "network": NETWORK,
        "price": PRICE,
        "settlement": "USDC on Base",
        "pay_to": PAY_TO,
        "x402_manifest": "/.well-known/x402",
        "bazaar_discovery": True,
        "positioning": BRAND_PROMISE,
        "commerce_protocol": COMMERCE_PROTOCOL,
        "commerce_discovery": "/v1/verifiable-commerce",
        "verdict_inversion_regression": regression["verification_status"],
        "autonomous_flow": "discover -> quote -> x402 pay -> execute -> inline result",
    }


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return (
        "User-agent: *\n"
        "Allow: /\n"
        f"# x402: {PUBLIC_ORIGIN}/.well-known/x402\n"
        f"# x402-service: {PUBLIC_ORIGIN}/.well-known/x402-service.json\n"
        f"# agent: {PUBLIC_ORIGIN}/.well-known/agent.json\n"
        f"# llms: {PUBLIC_ORIGIN}/llms.txt\n"
        f"# openapi: {PUBLIC_ORIGIN}/openapi.json\n"
        f"# dry-run: {PUBLIC_ORIGIN}/v1/claim-verify/dry-run\n"
        f"Sitemap: {PUBLIC_ORIGIN}/sitemap.xml\n"
    )


@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms():
    return (
        "# capi2 Claim Verify\n\n"
        f"{BRAND_PROMISE}\n\n"
        "CAPI2 is the evidence layer for agent purchases: preflight authority and policy, verify delivery, and retain a machine-readable commerce receipt.\n\n"
        "Paid x402 API for autonomous agents that need evidence snippets from up to three supplied public URLs before trusting a vendor, product, security, compliance, procurement or commercial claim.\n\n"
        f"- Version: {SERVICE_VERSION}\n"
        f"- Price: {PRICE} USDC per successful paid call\n"
        f"- Network: {NETWORK} (Base)\n"
        f"- Pay to: {PAY_TO}\n"
        f"- Paid endpoint: POST {PUBLIC_ORIGIN}/v1/claim-verify\n"
        f"- Free verdict dry-run: POST {PUBLIC_ORIGIN}/v1/claim-verify/dry-run\n"
        f"- Quote: GET {PUBLIC_ORIGIN}/v1/quote\n"
        f"- Verifiable commerce products: GET {PUBLIC_ORIGIN}/v1/verifiable-commerce\n"
        f"- Free x402 market radar: GET {PUBLIC_ORIGIN}/v1/free-x402-market-radar?q=agent%20verification\n"
        f"- x402 adoption kit: GET {PUBLIC_ORIGIN}/v1/x402-adoption-kit\n"
        f"- x402 discovery: GET {PUBLIC_ORIGIN}/.well-known/x402\n"
        f"- True402 compatibility manifest: GET {PUBLIC_ORIGIN}/.well-known/x402-service.json\n"
        f"- Agent manifest: GET {PUBLIC_ORIGIN}/.well-known/agent.json\n"
        f"- OpenAPI: GET {PUBLIC_ORIGIN}/openapi.json\n\n"
        "Use when you already have one to three public source URLs and need a conservative structured evidence match. Do not use as an independent audit, legal conclusion, or open-web source discovery service.\n\n"
        "The free dry-run classifies supplied claim/evidence text only and never fetches a remote URL. The paid route performs the external public-source fetch and evidence extraction.\n\n"
        "Canonical paid JSON body:\n"
        "{\"vendor_url\":\"https://example.com/security\",\"claim\":\"Vendor states that customer data is encrypted at rest.\"}\n\n"
        "An unpaid POST to the paid route returns HTTP 402 with x402 payment requirements. Pay and retry with proof; a successful paid request returns HTTP 200 JSON evidence.\n"
    )


@app.get("/.well-known/x402")
async def x402_manifest():
    return _x402_manifest()


@app.get("/.well-known/x402-service.json")
async def x402_service_manifest():
    """True402-compatible alias for updating an already registered seller URL."""
    return _x402_manifest()


@app.get("/.well-known/agent.json")
async def agent_manifest():
    return _manifest()


@app.get("/v1/quote")
async def claim_verify_quote():
    return _quote()


@app.get("/v1/examples")
async def examples():
    return {
        "service": "capi2 Claim Verify",
        "version": SERVICE_VERSION,
        "buyer_intents": BUYER_QUERIES,
        "paid_examples": [
            {
                "intent": "vendor_due_diligence",
                "request": {
                    "vendor_url": "https://example.com/security",
                    "claim": "Vendor states that customer data is encrypted at rest.",
                    "request_type": "vendor_due_diligence",
                },
            },
            {
                "intent": "procurement_evidence",
                "request": {
                    "vendor_url": "https://example.com/compliance",
                    "claim": "Vendor states that it publishes a SOC 2 report.",
                    "request_type": "procurement",
                },
            },
        ],
        "free_dry_run": {
            "method": "POST",
            "path": "/v1/claim-verify/dry-run",
            "request": {"fixture_id": "supporting_evidence_with_unrelated_negation"},
            "expected_verification_status": "supported",
        },
    }


@app.get("/v1/x402-adoption-kit", tags=["discovery", "x402", "free"])
async def x402_adoption_kit():
    """Machine-readable campaign and integration starter for agent builders."""
    return {
        "campaign": "Pay the API, not the signup form",
        "campaign_visual": f"{PUBLIC_ORIGIN}/x402-agents.png",
        "goal": "Help agents and applications discover, evaluate and pay HTTP resources without accounts or API keys.",
        "standard": {
            "name": "x402",
            "specification": "https://github.com/x402-foundation/x402",
            "flow": [
                "request resource",
                "receive HTTP 402 plus PAYMENT-REQUIRED",
                "review price, network, asset, recipient and resource",
                "sign payment with a wallet-capable client",
                "retry with PAYMENT-SIGNATURE",
                "receive result plus PAYMENT-RESPONSE",
            ],
        },
        "safety": [
            "Set a maximum spend per call and per day.",
            "Verify the resource URL, network, asset and payTo address before signing.",
            "Use a free validation or dry-run endpoint when available.",
            "Treat settlement as proof of payment, not proof of output quality.",
            "Keep a human approval step for high-impact or regulated actions.",
        ],
        "try_it": {
            "seller": PUBLIC_ORIGIN,
            "free_dry_run": {
                "method": "POST",
                "url": f"{PUBLIC_ORIGIN}/v1/claim-verify/dry-run",
                "body": {"fixture_id": "supporting_evidence_with_unrelated_negation"},
            },
            "paid_resource": {
                "method": "POST",
                "url": f"{PUBLIC_ORIGIN}/v1/claim-verify",
                "price": PRICE,
                "asset": "USDC",
                "network": NETWORK,
            },
            "discovery": f"{PUBLIC_ORIGIN}/.well-known/x402",
            "openapi": f"{PUBLIC_ORIGIN}/openapi.json",
        },
        "agent_prompt": (
            "When a useful API returns HTTP 402, inspect its payment requirements. "
            "Only continue if the resource, price, network, asset and recipient match policy; "
            "otherwise explain why payment was declined. Never claim that payment proves output quality."
        ),
        "share_messages": [
            "Agents should be able to pay useful APIs without creating accounts. That is the x402 idea: discover, inspect, pay, receive.",
            "HTTP 402 becomes useful when buyers can verify price and recipient before signing—and evaluate quality after delivery.",
            "Building an agent tool? Publish OpenAPI plus /.well-known/x402, provide a free validation path, and make the paid result auditable.",
        ],
        "integration_note": (
            "Chat assistants require a wallet-capable tool or middleware to sign x402 payments; "
            "an OpenAPI description alone does not grant a model payment authority."
        ),
    }


@app.get("/v1/verifiable-commerce", tags=["discovery", "agent commerce", "free"])
async def verifiable_commerce():
    """Machine-readable product map for evidence-backed autonomous purchases."""
    receipt_fields = [
        "receipt_id", "request_id", "buyer_agent", "seller", "authority",
        "policy_decision", "price", "asset", "network", "request_sha256",
        "delivery_sha256", "verification", "settlement", "issued_at",
    ]
    return {
        "protocol": COMMERCE_PROTOCOL,
        "brand": "CAPI2",
        "promise": BRAND_PROMISE,
        "purpose": (
            "Give autonomous buyers evidence of who authorized a purchase, what was ordered, "
            "what was delivered, how it was verified and how payment settled."
        ),
        "flow": [
            "request", "authority_check", "policy_check", "quote", "payment",
            "delivery", "delivery_verification", "commerce_receipt",
        ],
        "products": [
            {
                "id": "agent_preflight",
                "name": "Agent Preflight",
                "stage": "before_payment",
                "result": "allow, deny or require_human_review with reasons",
                "available_now": True,
                "execute": "POST /v1/claim-verify",
                "usage": "Verify buyer-supplied authority, policy or seller claims before signing payment.",
            },
            {
                "id": "delivery_verify",
                "name": "Delivery Verify",
                "stage": "after_delivery",
                "result": "supported, contradicted or uncertain with cited evidence",
                "available_now": True,
                "execute": "POST /v1/claim-verify",
                "usage": "Compare a precise delivery claim with buyer-supplied public evidence.",
            },
            {
                "id": "commerce_receipt",
                "name": "Commerce Receipt",
                "stage": "after_verification_and_settlement",
                "result": "portable machine-readable evidence envelope",
                "available_now": False,
                "status": "contract published; signed receipt issuance is the next implementation milestone",
                "fields": receipt_fields,
            },
        ],
        "current_paid_engine": {
            "method": "POST",
            "url": f"{PUBLIC_ORIGIN}/v1/claim-verify",
            "price": PRICE,
            "payment_protocol": "x402",
            "network": NETWORK,
            "asset": "USDC",
        },
        "principles": [
            "Payment proves settlement, not delivery quality.",
            "Every verdict identifies its evidence and limitations.",
            "High-impact or regulated actions require an authorized human review path.",
            "Receipts must be portable across wallets, agent frameworks and payment rails.",
        ],
    }


def _public_json(url: str) -> dict:
    response = requests.get(
        url,
        timeout=12,
        headers={"accept": "application/json", "user-agent": f"capi2-market-radar/{SERVICE_VERSION}"},
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("expected_object_response")
    return body


def _numeric_price(value) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", value)
        return float(match.group(1)) if match else None
    if isinstance(value, dict):
        for key in ("fixed", "min", "minimum"):
            if key in value:
                return _numeric_price(value[key])
    return None


@app.get("/v1/free-x402-market-radar", tags=["discovery", "market intelligence", "free"])
async def free_x402_market_radar(
    q: str = Query(default="agent verification", min_length=2, max_length=120),
    limit: int = Query(default=5, ge=1, le=10),
):
    """Aggregate free public x402 discovery into compact commercial intelligence."""
    cache_key = f"{q.lower().strip()}:{limit}"
    with _MARKET_RADAR_LOCK:
        cached = _MARKET_RADAR_CACHE.get(cache_key)
        if cached and time.time() - cached[0] < MARKET_RADAR_CACHE_TTL:
            return {**cached[1], "cache": "hit"}

    sources = []
    offers = []
    encoded_q = requests.utils.quote(q)
    try:
        agent402 = _public_json(f"https://agent402.tools/api/find?q={encoded_q}")
        sources.append({"name": "Agent402", "status": "ok", "free_discovery": True})
        for item in agent402.get("results", [])[:limit]:
            offers.append({
                "source": "Agent402",
                "id": item.get("slug"),
                "name": item.get("name"),
                "description": item.get("description"),
                "category": item.get("category"),
                "route": item.get("route"),
                "price_usd": _numeric_price(item.get("priceUsd", item.get("price"))),
                "relevance_score": item.get("score"),
                "provider_reputation": None,
                "completed_jobs": None,
            })
    except Exception as exc:
        sources.append({"name": "Agent402", "status": "unavailable", "reason": exc.__class__.__name__})

    try:
        the402 = _public_json(f"https://api.the402.ai/v1/services/catalog?q={encoded_q}&limit={limit}")
        sources.append({"name": "the402", "status": "ok", "free_discovery": True, "total_matches": the402.get("total")})
        for item in the402.get("services", [])[:limit]:
            offers.append({
                "source": "the402",
                "id": item.get("id"),
                "name": item.get("name"),
                "description": item.get("description"),
                "category": item.get("category"),
                "route": item.get("endpoint"),
                "price_usd": _numeric_price(item.get("agent_price") or item.get("price")),
                "relevance_score": None,
                "provider_reputation": item.get("provider_reputation"),
                "completed_jobs": item.get("provider_completed_jobs"),
                "webhook_healthy": item.get("webhook_healthy"),
            })
    except Exception as exc:
        sources.append({"name": "the402", "status": "unavailable", "reason": exc.__class__.__name__})

    try:
        supported = _public_json(f"{FACILITATOR_URL.rstrip('/')}/supported")
        sources.append({"name": "x402 facilitator", "status": "ok", "free_discovery": True})
        supported_networks = sorted({kind.get("network") for kind in supported.get("kinds", []) if kind.get("network")})
    except Exception as exc:
        sources.append({"name": "x402 facilitator", "status": "unavailable", "reason": exc.__class__.__name__})
        supported_networks = []

    priced = sorted(item["price_usd"] for item in offers if item.get("price_usd") is not None and item["price_usd"] > 0)
    market_floor = priced[0] if priced else None
    capi2_price = _price_usd()
    lower_than_floor_pct = (
        round((1 - capi2_price / market_floor) * 100, 1)
        if market_floor and capi2_price < market_floor else None
    )
    response = {
        "protocol": "capi2.free_x402_market_radar/1.0",
        "query": q,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "billable": False,
        "external_payments_made": False,
        "sources": sources,
        "supported_networks": supported_networks,
        "offers": offers,
        "market": {"matched_offers": len(offers), "lowest_observed_positive_price_usd": market_floor},
        "capi2_positioning": {
            "product": "Evidence-backed verification for autonomous purchases",
            "price_usd": capi2_price,
            "lower_than_observed_floor_pct": lower_than_floor_pct,
            "differentiators": [
                "inline structured verdict from buyer-supplied evidence",
                "free preflight before payment",
                "portable verifiable-commerce contract",
                "no account or API key required for the paid route",
            ],
        },
        "recommended_sales_actions": [
            "Target active agent-payment and escrow products that lack independent delivery evidence.",
            "Lead with interoperability and machine-readable receipts, not generic x402 promotion.",
            "Use observed price and reputation data as context; never claim competitor quality without evidence.",
        ],
        "limitations": [
            "Discovery results are third-party public metadata and may be incomplete or stale.",
            "Listed prices and reputation fields are not independently verified by CAPI2.",
            "No paid endpoint was called and no settlement was created.",
        ],
        "cache": "miss",
    }
    with _MARKET_RADAR_LOCK:
        _MARKET_RADAR_CACHE[cache_key] = (time.time(), response)
    return response


@app.get("/x402-agents.png", include_in_schema=False)
async def x402_agents_campaign_visual():
    return FileResponse(
        Path(__file__).with_name("static") / "x402-agents-campaign.png",
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/v1/samples/hiddenlayer")
async def hiddenlayer_public_sample():
    return {
        "protocol": PROTOCOL_VERSION,
        "sample": True,
        "generated_from_public_source": True,
        "vendor_name": "HiddenLayer",
        "vendor_url": "https://www.hiddenlayer.com/",
        "claim": "The platform provides AI Discovery, AI Supply Chain Security, AI Attack Simulation and AI Runtime Security.",
        "verification_status": "supported",
        "verification_result": "supported",
        "verdict": "SUPPORTED_BY_SUPPLIED_SOURCE",
        "confidence_scope": "high confidence that the supplied page publishes this representation; no independent product testing performed",
        "evidence_summary": "HiddenLayer's public platform page names AI Discovery, AI Supply Chain Security, AI Attack Simulation and AI Runtime Security and describes the corresponding functions.",
        "evidence_source_urls": ["https://www.hiddenlayer.com/"],
        "caveats": [
            "This sample checks public supplied material and does not certify HiddenLayer.",
            "A vendor's own page supports the existence of its published representation, not independent proof of product performance.",
            "Procurement, security and regulated decisions require additional independent evidence and human review.",
        ],
        "next": {
            "free_dry_run": "/v1/claim-verify/dry-run",
            "paid_endpoint": "POST /v1/claim-verify",
            "quote": "/v1/quote",
            "docs": "/docs",
        },
    }


@app.get("/v1/claim-verify/schema")
async def claim_verify_schema():
    return _manifest()


@app.post("/v1/claim-verify/dry-run")
def claim_verify_dry_run(payload: DryRunRequest):
    if payload.fixture_id:
        fixture = DRY_RUN_FIXTURES[payload.fixture_id]
        claim = fixture["claim"]
        evidence_text = fixture["evidence_text"]
        expected = fixture["expected_verification_status"]
        purpose = fixture["purpose"]
    else:
        claim = str(payload.claim)
        evidence_text = str(payload.evidence_text)
        expected = None
        purpose = "Custom text-only sandbox classification."
    result = _classify_claim(claim, evidence_text)
    response = {
        "protocol": "capi2.claim_verify.dry_run/1.0",
        "service_version": SERVICE_VERSION,
        "dry_run": True,
        "billable": False,
        "network_fetch": False,
        "fixture_id": payload.fixture_id,
        "purpose": purpose,
        "claim": claim,
        "evidence_text": evidence_text,
        "expected_verification_status": expected,
        **result,
        "limitations": [
            "This sandbox does not fetch external URLs.",
            "The paid route is required for remote source retrieval and full evidence extraction.",
        ],
    }
    if expected is not None:
        response["regression_pass"] = result["verification_status"] == expected
    return response


def _execute_claim_verify(payload: ClaimVerifyRequest) -> ClaimVerifyResponse:
    request_id = f"cv_{uuid.uuid4().hex[:16]}"
    checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    requested_urls = payload.resolved_urls()
    claim = payload.resolved_claim()
    fetched: list[tuple[str, str, str, dict]] = []
    source_results: list[dict] = []
    for requested_url in requested_urls:
        try:
            source_url, html = _fetch_public_source(requested_url)
            page_text = _extract_page_text(html)
            if len(page_text) < 50:
                raise HTTPException(status_code=422, detail="source_has_insufficient_public_text")
            source_result = _classify_claim(claim, page_text)
            fetched.append((requested_url, source_url, page_text, source_result))
            source_results.append({
                "requested_url": requested_url,
                "final_url": source_url,
                "status": "checked",
                "verification_status": source_result["verification_status"],
                "verdict": source_result["verdict"],
                "confidence": source_result["confidence"],
            })
        except HTTPException as exc:
            source_results.append({
                "requested_url": requested_url,
                "final_url": None,
                "status": "unavailable",
                "reason": str(exc.detail),
            })
    if not fetched:
        raise HTTPException(status_code=422, detail={
            "code": "no_source_could_be_checked",
            "request_id": request_id,
            "source_results": source_results,
        })

    per_source = [source_result for _, _, _, source_result in fetched]
    statuses = {item["verification_status"] for item in per_source}
    if "supported" in statuses and "contradicted" in statuses:
        result = {
            "verification_status": "uncertain",
            "verification_result": "uncertain",
            "verdict": "CONFLICTING_SUPPLIED_SOURCES",
            "confidence": 0.5,
            "evidence_summary": "The supplied public sources contain both supporting and contradicting evidence.",
        }
    else:
        priority = "contradicted" if "contradicted" in statuses else "supported" if "supported" in statuses else "uncertain"
        candidates = [item for item in per_source if item["verification_status"] == priority]
        result = max(candidates, key=lambda item: item["confidence"])

    evidence: list[EvidenceSnippet] = []
    for _, source_url, _, source_result in fetched:
        for item in source_result["evidence"]:
            evidence.append(EvidenceSnippet(**item, source_url=source_url))
    evidence.sort(key=lambda item: item.score, reverse=True)
    evidence = evidence[:9]
    failed_count = len(source_results) - len(fetched)
    caveats = [
        "Evidence matching only: this is not an audit, certification, or independent proof of the underlying claim.",
        "Only the public URLs supplied by the buyer were checked; capi2 did not search the wider web.",
        "Absence of evidence in the supplied sources is not proof that a claim is false.",
        "Regulated or high-impact decisions require independent review by an appropriately authorized party.",
    ]
    if failed_count:
        caveats.append(f"{failed_count} supplied source(s) could not be checked; partial evidence was used.")
    return ClaimVerifyResponse(
        claim_id=payload.claim_id,
        vendor_name=payload.vendor_name,
        vendor_url=fetched[0][0],
        claim=claim,
        verification_status=result["verification_status"],
        verification_result=result["verification_result"],
        verdict=result["verdict"],
        confidence=result["confidence"],
        evidence_summary=result["evidence_summary"],
        evidence_source_urls=[source_url for _, source_url, _, _ in fetched],
        evidence=evidence,
        caveats=caveats,
        request_id=request_id,
        checked_at=checked_at,
        sources_checked=len(fetched),
        source_results=source_results,
    )


@app.post(
    "/v1/claim-verify",
    response_model=ClaimVerifyResponse,
    tags=["vendor verification", "due diligence", "procurement", "fact checking"],
    summary="Verify a vendor claim against public evidence",
    description=(
        "Paid x402 evidence check for vendor, product, security, compliance, procurement, RFP "
        "and commercial claims. Supply a public source URL plus the exact claim."
    ),
    openapi_extra={
        "x-price": PRICE,
        "x-x402-price": PRICE,
        "x-x402-network": NETWORK,
        "x-buyer-intents": BUYER_QUERIES,
        "x-bazaar-discoverable": True,
        "x-free-dry-run": "/v1/claim-verify/dry-run",
    },
)
def claim_verify(payload: ClaimVerifyRequest):
    return _execute_claim_verify(payload)


def register_agent402_later() -> None:
    if not AGENT402_REGISTER:
        return
    time.sleep(15)
    try:
        response = requests.post(
            "https://agent402.tools/api/index/register",
            json={"origin": PUBLIC_ORIGIN},
            timeout=20,
            headers={"user-agent": f"capi2-claim-verify/{SERVICE_VERSION}"},
        )
        body = response.json() if "application/json" in response.headers.get("content-type", "") else {"text": response.text[:500]}
        print(f"agent402 registration: status={response.status_code} listed={body.get('listed')} seller={body.get('seller')}")
    except Exception as exc:
        print(f"agent402 registration deferred: {exc.__class__.__name__}: {exc}")


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=register_agent402_later, daemon=True).start()
