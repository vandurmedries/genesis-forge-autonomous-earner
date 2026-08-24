import ipaddress
import os
import re
import socket
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, HttpUrl, model_validator

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

PAY_TO = os.getenv("CAPI2_PAY_TO", "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a")
NETWORK = os.getenv("CAPI2_X402_NETWORK", "eip155:8453")
FACILITATOR_URL = os.getenv("CAPI2_X402_FACILITATOR", "https://facilitator.payai.network")
PRICE = os.getenv("CAPI2_CLAIM_VERIFY_PRICE", "$0.01")
MAX_SOURCE_BYTES = int(os.getenv("CAPI2_MAX_SOURCE_BYTES", "2000000"))
MAX_REDIRECTS = 3

app = FastAPI(
    title="capi2 Claim Verify",
    version="1.3.0",
    description="Agent-discoverable public-evidence vendor claim verification with x402 payment on Base USDC.",
)

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
server = x402ResourceServer(facilitator)
server.register(NETWORK, ExactEvmServerScheme())

routes = {
    "POST /v1/claim-verify": RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                pay_to=PAY_TO,
                price=PRICE,
                network=NETWORK,
            )
        ],
        mime_type="application/json",
        description="Verify one public vendor claim against a supplied public source URL and return machine-readable evidence.",
    )
}

app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


class ClaimVerifyRequest(BaseModel):
    vendor_url: Optional[HttpUrl] = None
    claim: Optional[str] = Field(default=None, min_length=3, max_length=1200)

    # Agent-to-agent compatibility aliases used by current buyers/routers.
    context_url: Optional[HttpUrl] = None
    claim_to_verify: Optional[str] = Field(default=None, min_length=3, max_length=1200)
    claim_text: Optional[str] = Field(default=None, min_length=3, max_length=1200)
    vendor_name: Optional[str] = Field(default=None, max_length=200)
    claim_id: Optional[str] = Field(default=None, max_length=200)
    request_type: Optional[str] = Field(default=None, max_length=120)
    verification_type: Optional[str] = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def require_resolvable_input(self):
        if self.vendor_url is None and self.context_url is None:
            raise ValueError("vendor_url or context_url is required")
        if not (self.claim or self.claim_to_verify or self.claim_text):
            raise ValueError("claim, claim_to_verify, or claim_text is required")
        return self

    def resolved_url(self) -> str:
        return str(self.vendor_url or self.context_url)

    def resolved_claim(self) -> str:
        return str(self.claim or self.claim_to_verify or self.claim_text)


class EvidenceSnippet(BaseModel):
    text: str
    score: float


class ClaimVerifyResponse(BaseModel):
    protocol: str = "capi2.claim_verify/1.3"
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


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 4
    }


def _sentence_chunks(text: str) -> List[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [re.sub(r"\s+", " ", c).strip() for c in chunks if len(c.strip()) >= 25]


def _has_negation(text: str) -> bool:
    normalized = f" {re.sub(r'[^a-z0-9]+', ' ', text.lower())} "
    markers = (
        " not ",
        " no ",
        " never ",
        " without ",
        " does not ",
        " do not ",
        " cannot ",
        " is not ",
        " are not ",
        " lacks ",
        " lacking ",
    )
    return any(marker in normalized for marker in markers)


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
    headers = {"User-Agent": "capi2-claim-verify/1.3 (+public-evidence-check)"}

    for _ in range(MAX_REDIRECTS + 1):
        _validate_public_http_url(current)
        try:
            response = requests.get(
                current,
                timeout=(4, 12),
                allow_redirects=False,
                stream=True,
                headers=headers,
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


def _lifecycle() -> list[dict]:
    return [
        {
            "step": "discover",
            "method": "GET",
            "path": "/.well-known/agent.json",
            "payment_required": False,
        },
        {
            "step": "quote",
            "method": "GET",
            "path": "/v1/quote",
            "payment_required": False,
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
            "behavior": "After x402 verification/settlement, capi2 executes the requested claim-verification task.",
        },
        {
            "step": "result",
            "mode": "inline",
            "success_status": 200,
            "content_type": "application/json",
            "behavior": "The paid request returns the machine-readable result directly in the successful response.",
        },
    ]


def _quote() -> dict:
    return {
        "protocol": "capi2.quote/1.0",
        "service": "claim_verify",
        "description": "Verify one public vendor claim against one supplied public source URL.",
        "price": PRICE,
        "asset": "USDC",
        "network": NETWORK,
        "payment_protocol": "x402",
        "pay_to": PAY_TO,
        "execute": {
            "method": "POST",
            "path": "/v1/claim-verify",
            "content_type": "application/json",
        },
        "result": {
            "mode": "inline",
            "success_status": 200,
            "content_type": "application/json",
        },
        "marketplace": {
            "standard_fee_bps": 1000,
            "provider_share_bps": 9000,
            "note": "The 10/90 split applies to routed third-party marketplace jobs after successful delivery and provider payout onboarding; this first-party capi2 Claim Verify service settles to the configured capi2 pay_to address.",
        },
    }


def _manifest() -> dict:
    return {
        "name": "capi2 Claim Verify",
        "protocol": "capi2.claim_verify/1.3",
        "description": "Verify a public vendor claim against a supplied public source URL.",
        "discovery": "/.well-known/agent.json",
        "openapi": "/openapi.json",
        "quote": {"method": "GET", "path": "/v1/quote"},
        "endpoint": {"method": "POST", "path": "/v1/claim-verify"},
        "lifecycle": _lifecycle(),
        "payment": {
            "protocol": "x402",
            "network": NETWORK,
            "asset": "USDC",
            "price": PRICE,
            "payTo": PAY_TO,
        },
        "input": {
            "canonical": {"vendor_url": "https://...", "claim": "..."},
            "aliases": [
                ["context_url", "claim_to_verify"],
                ["vendor_url", "claim_text"],
            ],
            "optional": ["vendor_name", "claim_id", "request_type", "verification_type"],
        },
        "output": {
            "delivery": "inline_after_successful_payment_and_execution",
            "status_fields": ["verification_status", "verification_result"],
            "status_values": ["supported", "contradicted", "uncertain"],
            "evidence_fields": ["evidence_summary", "evidence_source_urls", "evidence"],
        },
    }


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "capi2-claim-verify",
        "version": "1.3.0",
        "network": NETWORK,
        "price": PRICE,
        "settlement": "USDC on Base",
        "pay_to": PAY_TO,
        "autonomous_flow": "discover -> quote -> x402 pay -> execute -> inline result",
    }


@app.get("/.well-known/agent.json")
async def agent_manifest():
    return _manifest()


@app.get("/v1/quote")
async def claim_verify_quote():
    return _quote()


@app.get("/v1/claim-verify/schema")
async def claim_verify_schema():
    return _manifest()


@app.post("/v1/claim-verify", response_model=ClaimVerifyResponse)
def claim_verify(payload: ClaimVerifyRequest):
    requested_url = payload.resolved_url()
    claim = payload.resolved_claim()
    source_url, html = _fetch_public_source(requested_url)

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    page_text = soup.get_text(" ", strip=True)
    if len(page_text) < 50:
        raise HTTPException(status_code=422, detail="source_has_insufficient_public_text")

    claim_tokens = _tokens(claim)
    if not claim_tokens:
        raise HTTPException(status_code=422, detail="claim_has_insufficient_terms")

    ranked = []
    for chunk in _sentence_chunks(page_text):
        chunk_tokens = _tokens(chunk)
        if not chunk_tokens:
            continue
        overlap = len(claim_tokens & chunk_tokens)
        score = overlap / max(len(claim_tokens), 1)
        if overlap:
            ranked.append((score, chunk[:420]))

    ranked.sort(key=lambda x: x[0], reverse=True)
    top = ranked[:3]
    best = top[0][0] if top else 0.0
    best_text = top[0][1] if top else ""

    claim_negated = _has_negation(claim)
    evidence_negated = _has_negation(best_text) if best_text else False

    if best >= 0.60 and claim_negated == evidence_negated:
        verification_status = "supported"
        verdict = "SUPPORTED_BY_SUPPLIED_SOURCE"
    elif best >= 0.55 and claim_negated != evidence_negated:
        verification_status = "contradicted"
        verdict = "CONTRADICTED_BY_SUPPLIED_SOURCE"
    else:
        verification_status = "uncertain"
        verdict = "NOT_CONFIRMED_OR_AMBIGUOUS"

    evidence = [EvidenceSnippet(text=text, score=round(score, 3)) for score, text in top]
    confidence = min(0.95, round(0.25 + best * 0.70, 3))
    evidence_summary = best_text or "No sufficiently overlapping public statement was found on the supplied source."

    return ClaimVerifyResponse(
        claim_id=payload.claim_id,
        vendor_name=payload.vendor_name,
        vendor_url=requested_url,
        claim=claim,
        verification_status=verification_status,
        verification_result=verification_status,
        verdict=verdict,
        confidence=confidence,
        evidence_summary=evidence_summary,
        evidence_source_urls=[source_url],
        evidence=evidence,
        caveats=[
            "This checks only the supplied public URL and does not certify the vendor.",
            "Absence of evidence on the supplied page is not proof that a claim is false.",
            "Contradiction detection is heuristic and should be independently reviewed for consequential use.",
            "Regulated or high-impact decisions require independent review by an appropriately authorized party.",
        ],
    )
