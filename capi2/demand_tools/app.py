import base64
import hashlib
import html as html_lib
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field, HttpUrl

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

from .revenue_ops import install as install_revenue_ops

PAY_TO = os.getenv("CAPI2_PAY_TO", "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a")
NETWORK = os.getenv("CAPI2_X402_NETWORK", "eip155:8453")
FACILITATOR_URL = os.getenv("CAPI2_X402_FACILITATOR", "https://facilitator.payai.network")
MICRO_PRICE = os.getenv("CAPI2_DEMAND_TOOL_PRICE", "$0.001")
INTEL_PRICE = os.getenv("CAPI2_INTELLIGENCE_TOOL_PRICE", "$0.01")
PUBLIC_ORIGIN = os.getenv("CAPI2_DEMAND_TOOLS_ORIGIN", "https://capi2-demand-tools.onrender.com").rstrip("/")
AGENT402_REGISTER = os.getenv("CAPI2_AGENT402_REGISTER", "true").lower() == "true"
MAX_FETCH_BYTES = int(os.getenv("CAPI2_INTELLIGENCE_MAX_FETCH_BYTES", "750000"))
MAX_REDIRECTS = 3
USER_AGENT = "capi2-agent-intelligence/2.0 (+x402; public-data-only)"

app = FastAPI(
    title="capi2 Agent Utilities",
    version="2.0.0",
    description=(
        "Paid x402 utilities and live intelligence for autonomous agents: hashing/encoding plus "
        "public web lookup, domain intelligence, API discovery audit, evidence extraction and x402 health."
    ),
)

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
server = x402ResourceServer(facilitator)
server.register(NETWORK, ExactEvmServerScheme())
install_revenue_ops(server, PUBLIC_ORIGIN)

TEXT_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string", "minLength": 1, "description": "UTF-8 text to process."}},
    "required": ["text"],
}
BASE64_DECODE_SCHEMA = {
    "type": "object",
    "properties": {
        "data": {"type": "string", "minLength": 1, "description": "Base64 or Base64URL string."},
        "urlsafe": {"type": "boolean", "default": False},
    },
    "required": ["data"],
}
JWT_SCHEMA = {
    "type": "object",
    "properties": {"token": {"type": "string", "minLength": 3, "description": "JWT compact serialization."}},
    "required": ["token"],
}
JSON_CANONICALIZE_SCHEMA = {
    "type": "object",
    "properties": {"value": {"description": "Any JSON value to canonicalize."}},
    "required": ["value"],
}
WEB_LOOKUP_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "format": "uri", "description": "Public HTTP(S) URL to fetch live."},
        "query": {"type": ["string", "null"], "maxLength": 500, "description": "Optional question/keywords used to rank passages."},
        "max_bytes": {"type": "integer", "minimum": 1000, "maximum": MAX_FETCH_BYTES, "default": 200000},
    },
    "required": ["url"],
}
DOMAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string", "description": "Public DNS domain, e.g. example.com."},
        "include_rdap": {"type": "boolean", "default": True},
    },
    "required": ["domain"],
}
ORIGIN_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "format": "uri", "description": "Public API, agent or x402 URL; its origin and discovery surfaces are audited."}
    },
    "required": ["url"],
}
EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "format": "uri", "description": "Public source URL."},
        "query": {"type": "string", "minLength": 2, "maxLength": 1000, "description": "Claim, question or evidence terms."},
        "max_passages": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
    },
    "required": ["url", "query"],
}

BUYER_QUERIES = [
    "live web or public API lookup",
    "domain dns rdap tls intelligence",
    "audit an API or agent endpoint",
    "extract evidence from a public webpage",
    "check x402 agent health and discovery",
    "sha256 or sha512 checksum",
    "base64 encode or decode",
    "decode jwt claims",
    "canonicalize json",
]


def bazaar_body_extension(
    input_example: dict[str, Any],
    input_schema: dict[str, Any],
    output_example: dict[str, Any],
) -> dict[str, Any]:
    return {
        "bazaar": {
            "info": {
                "input": {"type": "http", "method": "POST", "bodyType": "json", "body": input_example},
                "output": {"type": "json", "example": output_example},
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
                            "body": input_schema,
                        },
                        "required": ["type", "method", "bodyType", "body"],
                        "additionalProperties": False,
                    },
                    "output": {
                        "type": "object",
                        "properties": {"type": {"type": "string"}, "example": {"type": "object"}},
                        "required": ["type"],
                    },
                },
                "required": ["input"],
            },
        }
    }


def _route(
    path: str,
    service_name: str,
    description: str,
    tags: list[str],
    input_example: dict[str, Any],
    input_schema: dict[str, Any],
    output_example: dict[str, Any],
    price: str,
) -> RouteConfig:
    return RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=PAY_TO, price=price, network=NETWORK)],
        resource=f"{PUBLIC_ORIGIN}{path}",
        mime_type="application/json",
        description=description,
        service_name=service_name,
        tags=tags,
        extensions=bazaar_body_extension(input_example, input_schema, output_example),
    )


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "path": "/v1/web/lookup",
        "name": "capi2 Live Web Lookup",
        "summary": "Fetch live public web/API data and return structured metadata, JSON or relevant text passages.",
        "description": "Live public HTTP(S) fetch for agents that need current webpage or API data without credentials.",
        "tags": ["web lookup", "live data", "public api", "web fetch", "agent research"],
        "buyer_queries": ["fetch a live public URL", "look up current public API data", "read webpage for an agent", "retrieve live web evidence"],
        "example": {"url": "https://example.com", "query": "example domain"},
        "schema": WEB_LOOKUP_SCHEMA,
        "output": {"status": 200, "content_type": "text/html", "title": "Example Domain", "passages": [{"text": "Example Domain", "score": 1.0}]},
        "price": INTEL_PRICE,
    },
    {
        "path": "/v1/domain/intelligence",
        "name": "capi2 Domain Intelligence",
        "summary": "Resolve DNS, RDAP, HTTPS and TLS intelligence for a public domain.",
        "description": "Public domain intelligence for vendor checks, infrastructure discovery, routing and security triage.",
        "tags": ["domain intelligence", "dns", "rdap", "tls", "vendor risk"],
        "buyer_queries": ["inspect domain dns records", "domain ownership and registrar intelligence", "check tls certificate and https", "vendor domain due diligence"],
        "example": {"domain": "example.com", "include_rdap": True},
        "schema": DOMAIN_SCHEMA,
        "output": {"domain": "example.com", "dns": {"A": ["93.184.216.34"]}, "https": {"status": 200}, "tls": {"available": True}},
        "price": INTEL_PRICE,
    },
    {
        "path": "/v1/api/audit",
        "name": "capi2 API Discovery Audit",
        "summary": "Audit a public API/agent origin for OpenAPI, x402, agent manifest, robots, llms and health surfaces.",
        "description": "Machine-readable discovery and API-readiness audit for public services and autonomous-agent endpoints.",
        "tags": ["api audit", "openapi", "agent discovery", "endpoint audit", "developer tools"],
        "buyer_queries": ["audit an api endpoint", "check openapi and agent manifests", "inspect api discovery readiness", "vendor api due diligence"],
        "example": {"url": "https://api.example.com/v1/tool"},
        "schema": ORIGIN_SCHEMA,
        "output": {"origin": "https://api.example.com", "score": 85, "grade": "A", "openapi": {"present": True}, "x402": {"present": True}},
        "price": INTEL_PRICE,
    },
    {
        "path": "/v1/evidence/extract",
        "name": "capi2 Evidence Extract",
        "summary": "Extract and rank evidence passages from a supplied public webpage for a question or claim.",
        "description": "Public-source evidence extraction that returns the strongest matching passages without making a consequential decision.",
        "tags": ["evidence extraction", "web research", "fact checking", "source analysis", "due diligence"],
        "buyer_queries": ["extract evidence from webpage", "find passages supporting a claim", "source evidence for due diligence", "webpage fact checking"],
        "example": {"url": "https://example.com", "query": "example domain", "max_passages": 5},
        "schema": EVIDENCE_SCHEMA,
        "output": {"source_url": "https://example.com", "passages": [{"text": "Example Domain", "score": 1.0}], "passage_count": 1},
        "price": INTEL_PRICE,
    },
    {
        "path": "/v1/x402/health",
        "name": "capi2 Agent x402 Health",
        "summary": "Check public agent/x402 discovery, manifests, resource exposure and operational health without paying.",
        "description": "Non-payment x402 health and discovery audit for agent sellers, marketplaces and routing systems.",
        "tags": ["x402 health", "agent health", "payment api", "discovery audit", "seller monitoring"],
        "buyer_queries": ["check x402 endpoint health", "is this agent seller discoverable", "audit x402 manifests and openapi", "monitor paid agent api health"],
        "example": {"url": "https://seller.example.com/v1/tool"},
        "schema": ORIGIN_SCHEMA,
        "output": {"status": "healthy", "score": 95, "x402_manifest": True, "resource_match": True, "payments_attempted": False},
        "price": INTEL_PRICE,
    },
    {
        "path": "/v1/hash/sha256",
        "name": "capi2 SHA-256",
        "summary": "SHA-256 digest for integrity checks, cache keys and deduplication.",
        "description": "Compute a SHA-256 checksum/digest for UTF-8 text.",
        "tags": ["sha256", "checksum", "integrity", "cache key", "deduplication"],
        "buyer_queries": ["sha256 checksum", "hash text", "content digest", "deduplicate content"],
        "example": {"text": "hello agent"},
        "schema": TEXT_SCHEMA,
        "output": {"algorithm": "sha256", "hex": "55ea...", "base64": "Veo...", "bytes": 11},
        "price": MICRO_PRICE,
    },
    {
        "path": "/v1/hash/sha512",
        "name": "capi2 SHA-512",
        "summary": "SHA-512 digest for integrity and deterministic workflows.",
        "description": "Compute a SHA-512 checksum/digest for UTF-8 text.",
        "tags": ["sha512", "checksum", "integrity", "digest", "developer tools"],
        "buyer_queries": ["sha512 checksum", "sha512 digest", "hash text with sha512"],
        "example": {"text": "hello agent"},
        "schema": TEXT_SCHEMA,
        "output": {"algorithm": "sha512", "hex": "db39...", "base64": "2zk...", "bytes": 11},
        "price": MICRO_PRICE,
    },
    {
        "path": "/v1/base64/encode",
        "name": "capi2 Base64 Encode",
        "summary": "Encode UTF-8 text to Base64.",
        "description": "Encode UTF-8 text to Base64 for API payloads and data transport.",
        "tags": ["base64", "encode", "api payload", "data transport", "developer tools"],
        "buyer_queries": ["base64 encode text", "encode api payload", "convert text to base64"],
        "example": {"text": "hello agent"},
        "schema": TEXT_SCHEMA,
        "output": {"encoding": "base64", "data": "aGVsbG8gYWdlbnQ=", "input_bytes": 11},
        "price": MICRO_PRICE,
    },
    {
        "path": "/v1/base64/decode",
        "name": "capi2 Base64 Decode",
        "summary": "Decode Base64 or Base64URL into UTF-8 text.",
        "description": "Decode Base64 or Base64URL data into UTF-8 text.",
        "tags": ["base64", "decode", "base64url", "api payload", "developer tools"],
        "buyer_queries": ["base64 decode", "decode base64url", "convert base64 to text"],
        "example": {"data": "aGVsbG8gYWdlbnQ=", "urlsafe": False},
        "schema": BASE64_DECODE_SCHEMA,
        "output": {"encoding": "base64", "text": "hello agent", "output_bytes": 11},
        "price": MICRO_PRICE,
    },
    {
        "path": "/v1/jwt/decode",
        "name": "capi2 JWT Decode",
        "summary": "Decode JWT header and claims without verifying the signature.",
        "description": "Decode JWT header and claims for inspection/debugging; signature verification is not performed.",
        "tags": ["jwt", "token inspection", "auth debugging", "decode", "developer tools"],
        "buyer_queries": ["decode jwt claims", "inspect jwt payload", "debug bearer token"],
        "example": {"token": "eyJhbGciOiJub25lIn0.eyJzdWIiOiIxMjMifQ."},
        "schema": JWT_SCHEMA,
        "output": {"header": {"alg": "none"}, "payload": {"sub": "123"}, "signature_present": False, "verified": False},
        "price": MICRO_PRICE,
    },
    {
        "path": "/v1/json/canonicalize",
        "name": "capi2 JSON Canonical",
        "summary": "Canonicalize JSON for stable hashing, signing and comparison.",
        "description": "Serialize JSON with sorted keys and compact separators.",
        "tags": ["json", "canonicalization", "signing", "deterministic", "hashing"],
        "buyer_queries": ["canonicalize json", "stable json for signing", "deterministic json hash"],
        "example": {"value": {"b": 2, "a": 1}},
        "schema": JSON_CANONICALIZE_SCHEMA,
        "output": {"canonical": "{\"a\":1,\"b\":2}", "sha256": "43258cff..."},
        "price": MICRO_PRICE,
    },
]

routes = {
    f"POST {spec['path']}": _route(
        spec["path"], spec["name"], spec["description"], spec["tags"],
        spec["example"], spec["schema"], spec["output"], spec["price"]
    )
    for spec in TOOL_SPECS
}
app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


class TextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200000)


class Base64Request(BaseModel):
    data: str = Field(min_length=1, max_length=300000)
    urlsafe: bool = False


class JwtRequest(BaseModel):
    token: str = Field(min_length=3, max_length=50000)


class JsonCanonicalizeRequest(BaseModel):
    value: Any


class WebLookupRequest(BaseModel):
    url: HttpUrl
    query: Optional[str] = Field(default=None, max_length=500)
    max_bytes: int = Field(default=200000, ge=1000, le=MAX_FETCH_BYTES)


class DomainIntelligenceRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=253)
    include_rdap: bool = True


class UrlAuditRequest(BaseModel):
    url: HttpUrl


class EvidenceExtractRequest(BaseModel):
    url: HttpUrl
    query: str = Field(min_length=2, max_length=1000)
    max_passages: int = Field(default=5, ge=1, le=10)


def _price_usd(value: str) -> float:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", value)
    return float(m.group(1)) if m else 0.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def b64url_decode(segment: str) -> bytes:
    pad = "=" * ((4 - len(segment) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(segment + pad)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="invalid_base64url_segment") from exc


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="url_must_be_public_http_or_https")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="embedded_credentials_not_allowed")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".local"):
        raise HTTPException(status_code=422, detail="private_hostname_blocked")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        resolved = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HTTPException(status_code=422, detail="dns_resolution_failed") from exc
    if not resolved:
        raise HTTPException(status_code=422, detail="dns_resolution_failed")
    for entry in resolved:
        ip = ipaddress.ip_address(entry[4][0])
        if not ip.is_global:
            raise HTTPException(status_code=422, detail="private_or_reserved_ip_blocked")


def _safe_fetch(url: str, max_bytes: int = 200000) -> dict[str, Any]:
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _validate_public_url(current)
        try:
            response = requests.get(
                current,
                timeout=(4, 12),
                allow_redirects=False,
                stream=True,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html,text/plain,*/*;q=0.5"},
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=422, detail=f"upstream_fetch_failed:{exc.__class__.__name__}") from exc

        if 300 <= response.status_code < 400:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise HTTPException(status_code=422, detail="redirect_without_location")
            current = urljoin(current, location)
            continue

        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            response.close()
            raise HTTPException(status_code=422, detail="upstream_response_too_large")

        raw = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                raw.extend(chunk)
                if len(raw) > max_bytes:
                    raise HTTPException(status_code=422, detail="upstream_response_too_large")
        finally:
            response.close()

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        encoding = response.encoding or "utf-8"
        body_text = bytes(raw).decode(encoding, errors="replace")
        return {
            "requested_url": url,
            "final_url": current,
            "status": response.status_code,
            "content_type": content_type,
            "headers": {
                key.lower(): value
                for key, value in response.headers.items()
                if key.lower() in {"content-type", "etag", "last-modified", "cache-control", "server"}
            },
            "raw": bytes(raw),
            "text": body_text,
        }

    raise HTTPException(status_code=422, detail="too_many_redirects")


def _html_to_text(value: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style|noscript|svg|template)\b.*?>.*?</\1>", " ", value)
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = html_lib.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _title_from_html(value: str) -> Optional[str]:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", value)
    if not match:
        return None
    return re.sub(r"\s+", " ", html_lib.unescape(match.group(1))).strip()[:300] or None


def _tokens(value: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", value.lower()) if len(t) >= 3}


def _passages(text: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+|\n+", text) if len(c.strip()) >= 20]
    ranked: list[tuple[float, str]] = []
    for chunk in chunks:
        chunk_tokens = _tokens(chunk)
        overlap = len(query_tokens & chunk_tokens)
        if not overlap:
            continue
        coverage = overlap / max(len(query_tokens), 1)
        density = overlap / max(len(chunk_tokens), 1)
        score = round(min(1.0, coverage * 0.8 + density * 0.2), 4)
        ranked.append((score, chunk[:700]))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [{"text": text_value, "score": score} for score, text_value in ranked[:limit]]


def _normalize_domain(value: str) -> str:
    domain = value.strip().rstrip(".").lower()
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise HTTPException(status_code=422, detail="invalid_domain") from exc
    if len(domain) > 253 or "." not in domain:
        raise HTTPException(status_code=422, detail="invalid_domain")
    labels = domain.split(".")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise HTTPException(status_code=422, detail="invalid_domain")
    try:
        ipaddress.ip_address(domain)
        raise HTTPException(status_code=422, detail="domain_name_required_not_ip")
    except ValueError:
        return domain


def _dns_lookup(domain: str, record_type: str) -> dict[str, Any]:
    try:
        response = requests.get(
            "https://dns.google/resolve",
            params={"name": domain, "type": record_type},
            timeout=(4, 8),
            headers={"User-Agent": USER_AGENT},
        )
        data = response.json()
    except Exception as exc:
        return {"status": "error", "error": exc.__class__.__name__, "answers": []}
    answers = []
    for answer in data.get("Answer", [])[:30]:
        if isinstance(answer, dict):
            answers.append({"type": answer.get("type"), "ttl": answer.get("TTL"), "data": answer.get("data")})
    return {"status": data.get("Status"), "answers": answers}


def _tls_info(domain: str) -> dict[str, Any]:
    try:
        _validate_public_url(f"https://{domain}/")
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as tls_sock:
                cert = tls_sock.getpeercert()
                cipher = tls_sock.cipher()
                return {
                    "available": True,
                    "version": tls_sock.version(),
                    "cipher": cipher[0] if cipher else None,
                    "subject": dict(x[0] for x in cert.get("subject", [])),
                    "issuer": dict(x[0] for x in cert.get("issuer", [])),
                    "not_before": cert.get("notBefore"),
                    "not_after": cert.get("notAfter"),
                    "subject_alt_names": [value for kind, value in cert.get("subjectAltName", []) if kind == "DNS"][:20],
                }
    except Exception as exc:
        return {"available": False, "error": exc.__class__.__name__}


def _rdap_summary(domain: str) -> dict[str, Any]:
    try:
        fetched = _safe_fetch(f"https://rdap.org/domain/{domain}", max_bytes=500000)
        data = json.loads(fetched["text"])
    except Exception as exc:
        return {"available": False, "error": exc.__class__.__name__}

    registrar = None
    for entity in data.get("entities", []) if isinstance(data, dict) else []:
        if "registrar" not in entity.get("roles", []):
            continue
        vcard = entity.get("vcardArray")
        if isinstance(vcard, list) and len(vcard) == 2 and isinstance(vcard[1], list):
            for item in vcard[1]:
                if isinstance(item, list) and len(item) >= 4 and item[0] == "fn":
                    registrar = item[3]
                    break
        if registrar:
            break

    events = {}
    for event in data.get("events", []) if isinstance(data, dict) else []:
        if isinstance(event, dict) and event.get("eventAction") and event.get("eventDate"):
            events[event["eventAction"]] = event["eventDate"]

    return {
        "available": True,
        "ldh_name": data.get("ldhName"),
        "handle": data.get("handle"),
        "status": data.get("status", []),
        "registrar": registrar,
        "events": events,
        "nameservers": [ns.get("ldhName") for ns in data.get("nameservers", []) if isinstance(ns, dict)][:20],
    }


def _origin_from_url(value: str) -> str:
    _validate_public_url(value)
    parsed = urlparse(value)
    return f"{parsed.scheme}://{parsed.netloc}"


def _surface(origin: str, path: str, max_bytes: int = 250000) -> dict[str, Any]:
    url = f"{origin}{path}"
    try:
        result = _safe_fetch(url, max_bytes=max_bytes)
        parsed_json = None
        if result["content_type"] in {"application/json", "application/problem+json"} or result["text"].lstrip().startswith(("{", "[")):
            try:
                parsed_json = json.loads(result["text"])
            except Exception:
                parsed_json = None
        return {
            "url": url,
            "present": 200 <= result["status"] < 300,
            "status": result["status"],
            "content_type": result["content_type"],
            "json": parsed_json,
        }
    except HTTPException as exc:
        return {"url": url, "present": False, "error": str(exc.detail)}


def _audit_discovery(url: str) -> dict[str, Any]:
    origin = _origin_from_url(url)
    parsed_target = urlparse(url)
    target_path = parsed_target.path or "/"
    surfaces = {
        "root": _surface(origin, "/", 80000),
        "openapi": _surface(origin, "/openapi.json", 400000),
        "x402": _surface(origin, "/.well-known/x402", 300000),
        "agent": _surface(origin, "/.well-known/agent.json", 300000),
        "robots": _surface(origin, "/robots.txt", 80000),
        "llms": _surface(origin, "/llms.txt", 160000),
        "health": _surface(origin, "/health", 120000),
    }

    openapi_data = surfaces["openapi"].get("json")
    x402_data = surfaces["x402"].get("json")
    operations = 0
    paid_operations = 0
    if isinstance(openapi_data, dict):
        for path_item in openapi_data.get("paths", {}).values():
            if not isinstance(path_item, dict):
                continue
            for method in ("get", "post", "put", "patch", "delete", "head", "options"):
                op = path_item.get(method)
                if isinstance(op, dict):
                    operations += 1
                    if op.get("x-payment-info") or op.get("x-x402-price") or op.get("x-price"):
                        paid_operations += 1

    resources: list[dict[str, Any]] = []
    if isinstance(x402_data, dict) and isinstance(x402_data.get("resources"), list):
        resources = [r for r in x402_data["resources"] if isinstance(r, dict)]
    target_url = f"{origin}{target_path}"
    resource_match = any(
        str(r.get("resource", "")).rstrip("/") == target_url.rstrip("/")
        or str(r.get("endpoint", "")).endswith(target_path)
        for r in resources
    )

    score = 0
    score += 10 if surfaces["root"].get("present") else 0
    score += 20 if surfaces["openapi"].get("present") else 0
    score += 20 if surfaces["x402"].get("present") else 0
    score += 10 if surfaces["agent"].get("present") else 0
    score += 5 if surfaces["robots"].get("present") else 0
    score += 5 if surfaces["llms"].get("present") else 0
    score += 10 if surfaces["health"].get("present") else 0
    score += 10 if resources else 0
    score += 10 if paid_operations else 0

    recommendations = []
    if not surfaces["openapi"].get("present"):
        recommendations.append("publish /openapi.json")
    if not surfaces["x402"].get("present"):
        recommendations.append("publish /.well-known/x402")
    if not surfaces["agent"].get("present"):
        recommendations.append("publish /.well-known/agent.json")
    if not surfaces["robots"].get("present"):
        recommendations.append("publish /robots.txt")
    if not surfaces["llms"].get("present"):
        recommendations.append("publish /llms.txt")
    if isinstance(openapi_data, dict) and not paid_operations and resources:
        recommendations.append("add x-payment-info/x402 pricing metadata to paid OpenAPI operations")
    if resources and target_path != "/" and not resource_match:
        recommendations.append("ensure the target paid resource is explicitly listed in /.well-known/x402")

    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D"
    return {
        "checked_at": _utc_now(),
        "target_url": url,
        "origin": origin,
        "target_path": target_path,
        "score": score,
        "grade": grade,
        "openapi": {
            "present": surfaces["openapi"].get("present", False),
            "operations": operations,
            "paid_operations": paid_operations,
        },
        "x402": {
            "present": surfaces["x402"].get("present", False),
            "resource_count": len(resources),
            "resource_match": resource_match,
        },
        "surfaces": {key: {k: v for k, v in value.items() if k != "json"} for key, value in surfaces.items()},
        "recommendations": recommendations,
    }


def _openapi_extra(price: str, buyer_queries: list[str]) -> dict[str, Any]:
    return {
        "x-price": price,
        "x-x402-price": price,
        "x-x402-network": NETWORK,
        "x-buyer-intents": buyer_queries,
        "x-bazaar-discoverable": True,
    }


def tool_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": spec["name"],
            "service_name": spec["name"],
            "endpoint": f"POST {spec['path']}",
            "resource": f"{PUBLIC_ORIGIN}{spec['path']}",
            "method": "POST",
            "price": spec["price"],
            "price_usd": _price_usd(spec["price"]),
            "tags": spec["tags"],
            "buyer_queries": spec["buyer_queries"],
            "example_request": spec["example"],
            "input_schema": spec["schema"],
            "summary": spec["summary"],
        }
        for spec in TOOL_SPECS
    ]


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "capi2 Agent Utilities",
        "paid": True,
        "asset": "USDC",
        "network": NETWORK,
        "micro_price": MICRO_PRICE,
        "intelligence_price": INTEL_PRICE,
        "buyer_queries": BUYER_QUERIES,
        "discover": {
            "human_page": f"{PUBLIC_ORIGIN}/buy",
            "x402": f"{PUBLIC_ORIGIN}/.well-known/x402",
            "agent": f"{PUBLIC_ORIGIN}/.well-known/agent.json",
            "openapi": f"{PUBLIC_ORIGIN}/openapi.json",
            "catalog": f"{PUBLIC_ORIGIN}/v1/catalog",
            "llms": f"{PUBLIC_ORIGIN}/llms.txt",
        },
        "tools": tool_catalog(),
    }


@app.get("/buy", response_class=HTMLResponse)
def buyer_page() -> str:
    return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>capi2 Agent Utilities</title><style>body{margin:0;background:#101814;color:#eaf3ed;font:16px/1.55 system-ui,sans-serif}.w{max-width:920px;margin:auto;padding:40px}.hero{padding:80px 0 45px}h1{font-size:clamp(44px,8vw,78px);line-height:.95;letter-spacing:-.05em;margin:0 0 22px}p{color:#aec0b7;font-size:19px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.card{border:1px solid #35443d;border-radius:15px;padding:20px;background:#16231d}.card b{font-size:18px}.btn{display:inline-block;background:#dff06a;color:#15231d;text-decoration:none;font-weight:850;padding:12px 17px;border-radius:10px;margin:10px 8px 0 0}@media(max-width:700px){.grid{grid-template-columns:1fr}}</style></head><body><main class="w"><section class="hero"><h1>Live intelligence. Stable outputs.</h1><p>Pay-per-call public web, domain, API and x402 intelligence plus deterministic hashing and encoding utilities for autonomous agents.</p><a class="btn" href="/v1/catalog">Browse tools and prices</a><a class="btn" href="/docs">Open API docs</a></section><section class="grid"><article class="card"><b>Due diligence</b><p>Inspect public domains, APIs and evidence before an agent acts.</p></article><article class="card"><b>Discovery health</b><p>Audit x402 and agent manifests, pricing and integration readiness.</p></article><article class="card"><b>Deterministic utilities</b><p>Hash, encode, inspect JWTs and canonicalize signing inputs.</p></article></section></main></body></html>"""


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "capi2-demand-tools",
        "version": "2.0.0",
        "network": NETWORK,
        "asset": "USDC",
        "micro_price": MICRO_PRICE,
        "intelligence_price": INTEL_PRICE,
        "pay_to": PAY_TO,
        "paid_tools": len(tool_catalog()),
        "bazaar_discovery": True,
        "positioning": "live public intelligence + x402 agent utilities",
        "revenue_ops": {
            "post_settlement_observer": True,
            "lago": bool(os.getenv("CAPI2_LAGO_WEBHOOK_URL")),
            "trigger": bool(os.getenv("CAPI2_TRIGGER_WEBHOOK_URL")),
            "crm": bool(os.getenv("CAPI2_CRM_WEBHOOK_URL")),
        },
    }


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> str:
    return (
        "User-agent: *\n"
        "Allow: /\n"
        f"# x402: {PUBLIC_ORIGIN}/.well-known/x402\n"
        f"# agent: {PUBLIC_ORIGIN}/.well-known/agent.json\n"
        f"# llms: {PUBLIC_ORIGIN}/llms.txt\n"
        f"# catalog: {PUBLIC_ORIGIN}/v1/catalog\n"
        f"# openapi: {PUBLIC_ORIGIN}/openapi.json\n"
    )


@app.get("/llms.txt", response_class=PlainTextResponse)
def llms() -> str:
    return "\n".join([
        "# capi2 Agent Utilities",
        "",
        "Paid x402 tools for autonomous agents.",
        f"- Live intelligence price: {INTEL_PRICE} USDC per call on {NETWORK}",
        f"- Deterministic microtool price: {MICRO_PRICE} USDC per call on {NETWORK}",
        f"- Pay to: {PAY_TO}",
        "",
        "High-intent tools:",
        f"- POST {PUBLIC_ORIGIN}/v1/web/lookup — live public web/API lookup",
        f"- POST {PUBLIC_ORIGIN}/v1/domain/intelligence — DNS/RDAP/TLS/domain intelligence",
        f"- POST {PUBLIC_ORIGIN}/v1/api/audit — API/OpenAPI/agent discovery audit",
        f"- POST {PUBLIC_ORIGIN}/v1/evidence/extract — public-source evidence passage extraction",
        f"- POST {PUBLIC_ORIGIN}/v1/x402/health — x402/agent discovery and health audit",
        "",
        f"x402 discovery: {PUBLIC_ORIGIN}/.well-known/x402",
        f"agent manifest: {PUBLIC_ORIGIN}/.well-known/agent.json",
        f"catalog: {PUBLIC_ORIGIN}/v1/catalog",
        f"OpenAPI: {PUBLIC_ORIGIN}/openapi.json",
        "",
        "All live intelligence tools accept public URLs/domains only. Private/reserved network targets and embedded credentials are blocked.",
        "An unpaid POST returns HTTP 402. Pay USDC on Base and retry with x402 proof for the JSON result.",
    ]) + "\n"


@app.get("/.well-known/x402")
def x402_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Agent Utilities",
        "description": "Live public web/domain/API/x402 intelligence plus low-cost deterministic utilities for autonomous agents.",
        "homepage": PUBLIC_ORIGIN,
        "protocol": "x402",
        "network": NETWORK,
        "asset": "USDC",
        "payTo": PAY_TO,
        "buyer_queries": BUYER_QUERIES,
        "resources": tool_catalog(),
        "free_endpoints": [
            "/", "/buy", "/health", "/robots.txt", "/llms.txt", "/.well-known/x402",
            "/.well-known/agent.json", "/openapi.json", "/v1/catalog",
        ],
    }


@app.get("/.well-known/agent.json")
def agent_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Agent Utilities",
        "protocol": "capi2.demand-tools/2.0.0",
        "description": "Live public intelligence and deterministic micro-APIs priced for autonomous agent purchasing.",
        "buyer_queries": BUYER_QUERIES,
        "discovery": {
            "x402": "/.well-known/x402",
            "openapi": "/openapi.json",
            "catalog": "/v1/catalog",
            "llms": "/llms.txt",
            "robots": "/robots.txt",
            "bazaar_extension": True,
        },
        "payment": {
            "protocol": "x402",
            "network": NETWORK,
            "asset": "USDC",
            "payTo": PAY_TO,
        },
        "tools": tool_catalog(),
    }


@app.get("/v1/catalog")
def catalog() -> dict[str, Any]:
    return {
        "count": len(tool_catalog()),
        "asset": "USDC",
        "network": NETWORK,
        "buyer_queries": BUYER_QUERIES,
        "tools": tool_catalog(),
    }


@app.post(
    "/v1/web/lookup",
    tags=["web lookup", "live data", "public api", "agent research"],
    summary="Live public web/API lookup",
    description="Fetch a public HTTP(S) URL live. Returns JSON when available or cleaned text plus query-ranked passages.",
    openapi_extra=_openapi_extra(INTEL_PRICE, TOOL_SPECS[0]["buyer_queries"]),
)
def web_lookup(payload: WebLookupRequest) -> dict[str, Any]:
    fetched = _safe_fetch(str(payload.url), max_bytes=payload.max_bytes)
    content_type = fetched["content_type"]
    body_text = fetched["text"]
    parsed_json = None
    title = None
    if content_type in {"application/json", "application/problem+json"} or body_text.lstrip().startswith(("{", "[")):
        try:
            parsed_json = json.loads(body_text)
        except Exception:
            parsed_json = None
    if "html" in content_type or "<html" in body_text[:500].lower():
        title = _title_from_html(body_text)
        clean_text = _html_to_text(body_text)
    else:
        clean_text = body_text.strip()
    result = {
        "fetched_at": _utc_now(),
        "requested_url": fetched["requested_url"],
        "final_url": fetched["final_url"],
        "status": fetched["status"],
        "content_type": content_type,
        "title": title,
        "bytes": len(fetched["raw"]),
        "sha256": hashlib.sha256(fetched["raw"]).hexdigest(),
        "headers": fetched["headers"],
        "json": parsed_json,
        "text_excerpt": clean_text[:12000] if parsed_json is None else None,
        "passages": _passages(clean_text, payload.query, 5) if payload.query else [],
    }
    return result


@app.post(
    "/v1/domain/intelligence",
    tags=["domain intelligence", "dns", "rdap", "tls", "vendor risk"],
    summary="Domain DNS/RDAP/TLS intelligence",
    description="Return public DNS records, selected RDAP registration metadata, HTTPS reachability and TLS certificate facts.",
    openapi_extra=_openapi_extra(INTEL_PRICE, TOOL_SPECS[1]["buyer_queries"]),
)
def domain_intelligence(payload: DomainIntelligenceRequest) -> dict[str, Any]:
    domain = _normalize_domain(payload.domain)
    dns = {record: _dns_lookup(domain, record) for record in ("A", "AAAA", "MX", "NS", "TXT", "CAA")}
    try:
        https = _safe_fetch(f"https://{domain}/", max_bytes=80000)
        https_summary = {
            "reachable": True,
            "status": https["status"],
            "final_url": https["final_url"],
            "content_type": https["content_type"],
            "server": https["headers"].get("server"),
            "title": _title_from_html(https["text"]) if "html" in https["content_type"] else None,
        }
    except HTTPException as exc:
        https_summary = {"reachable": False, "error": str(exc.detail)}
    return {
        "checked_at": _utc_now(),
        "domain": domain,
        "dns": dns,
        "https": https_summary,
        "tls": _tls_info(domain),
        "rdap": _rdap_summary(domain) if payload.include_rdap else {"skipped": True},
        "note": "Public technical/domain-registration metadata only; no private registrant data is returned.",
    }


@app.post(
    "/v1/api/audit",
    tags=["api audit", "openapi", "agent discovery", "endpoint audit"],
    summary="Audit public API and agent discovery",
    description="Check OpenAPI, x402, agent manifest, robots, llms and health surfaces and return a machine-readable readiness score.",
    openapi_extra=_openapi_extra(INTEL_PRICE, TOOL_SPECS[2]["buyer_queries"]),
)
def api_audit(payload: UrlAuditRequest) -> dict[str, Any]:
    result = _audit_discovery(str(payload.url))
    result["audit_type"] = "api_discovery"
    return result


@app.post(
    "/v1/evidence/extract",
    tags=["evidence extraction", "web research", "fact checking", "source analysis"],
    summary="Extract evidence passages from a public source",
    description="Fetch one public URL, clean the content, and rank passages relevant to the supplied question or claim.",
    openapi_extra=_openapi_extra(INTEL_PRICE, TOOL_SPECS[3]["buyer_queries"]),
)
def evidence_extract(payload: EvidenceExtractRequest) -> dict[str, Any]:
    fetched = _safe_fetch(str(payload.url), max_bytes=MAX_FETCH_BYTES)
    body = fetched["text"]
    if "html" in fetched["content_type"] or "<html" in body[:500].lower():
        title = _title_from_html(body)
        clean_text = _html_to_text(body)
    else:
        title = None
        clean_text = body.strip()
    passages = _passages(clean_text, payload.query, payload.max_passages)
    return {
        "extracted_at": _utc_now(),
        "source_url": fetched["final_url"],
        "source_status": fetched["status"],
        "content_type": fetched["content_type"],
        "title": title,
        "query": payload.query,
        "passages": passages,
        "passage_count": len(passages),
        "source_sha256": hashlib.sha256(fetched["raw"]).hexdigest(),
        "caveat": "Passages are ranked by lexical relevance; relevance is not proof that a claim is true.",
    }


@app.post(
    "/v1/x402/health",
    tags=["x402 health", "agent health", "payment api", "discovery audit"],
    summary="Check agent/x402 seller health",
    description="Audit public x402 and agent discovery surfaces without attaching payment or executing a paid operation.",
    openapi_extra=_openapi_extra(INTEL_PRICE, TOOL_SPECS[4]["buyer_queries"]),
)
def x402_health(payload: UrlAuditRequest) -> dict[str, Any]:
    audit = _audit_discovery(str(payload.url))
    score = audit["score"]
    status = "healthy" if score >= 80 else "degraded" if score >= 55 else "unhealthy"
    return {
        "checked_at": audit["checked_at"],
        "target_url": audit["target_url"],
        "origin": audit["origin"],
        "status": status,
        "score": score,
        "grade": audit["grade"],
        "x402_manifest": audit["x402"]["present"],
        "x402_resource_count": audit["x402"]["resource_count"],
        "resource_match": audit["x402"]["resource_match"],
        "openapi": audit["openapi"],
        "surfaces": audit["surfaces"],
        "recommendations": audit["recommendations"],
        "payments_attempted": False,
    }


@app.post(
    "/v1/hash/sha256",
    tags=["hashing", "sha256", "checksum", "integrity"],
    summary="SHA-256 hash text",
    description="Compute SHA-256 for UTF-8 text.",
    openapi_extra=_openapi_extra(MICRO_PRICE, TOOL_SPECS[5]["buyer_queries"]),
)
def sha256(payload: TextRequest) -> dict[str, Any]:
    raw = payload.text.encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return {"algorithm": "sha256", "hex": digest.hex(), "base64": base64.b64encode(digest).decode("ascii"), "bytes": len(raw)}


@app.post(
    "/v1/hash/sha512",
    tags=["hashing", "sha512", "checksum", "integrity"],
    summary="SHA-512 hash text",
    description="Compute SHA-512 for UTF-8 text.",
    openapi_extra=_openapi_extra(MICRO_PRICE, TOOL_SPECS[6]["buyer_queries"]),
)
def sha512(payload: TextRequest) -> dict[str, Any]:
    raw = payload.text.encode("utf-8")
    digest = hashlib.sha512(raw).digest()
    return {"algorithm": "sha512", "hex": digest.hex(), "base64": base64.b64encode(digest).decode("ascii"), "bytes": len(raw)}


@app.post(
    "/v1/base64/encode",
    tags=["base64", "encode", "encoding", "api payload"],
    summary="Base64 encode text",
    description="Encode UTF-8 text to Base64.",
    openapi_extra=_openapi_extra(MICRO_PRICE, TOOL_SPECS[7]["buyer_queries"]),
)
def base64_encode(payload: TextRequest, urlsafe: bool = False) -> dict[str, Any]:
    raw = payload.text.encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw) if urlsafe else base64.b64encode(raw)
    return {"encoding": "base64url" if urlsafe else "base64", "data": encoded.decode("ascii"), "input_bytes": len(raw)}


@app.post(
    "/v1/base64/decode",
    tags=["base64", "decode", "base64url", "api payload"],
    summary="Base64 decode text",
    description="Decode standard or URL-safe Base64 into UTF-8 text.",
    openapi_extra=_openapi_extra(MICRO_PRICE, TOOL_SPECS[8]["buyer_queries"]),
)
def base64_decode(payload: Base64Request) -> dict[str, Any]:
    data = payload.data.strip()
    pad = "=" * ((4 - len(data) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(data + pad) if payload.urlsafe else base64.b64decode(data + pad, validate=True)
        text = raw.decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=422, detail="invalid_base64_or_non_utf8_output") from exc
    return {"encoding": "base64url" if payload.urlsafe else "base64", "text": text, "output_bytes": len(raw)}


@app.post(
    "/v1/jwt/decode",
    tags=["jwt", "token", "decode", "auth debugging"],
    summary="Decode JWT claims",
    description="Decode JWT header and payload. Signature/claims are not verified.",
    openapi_extra=_openapi_extra(MICRO_PRICE, TOOL_SPECS[9]["buyer_queries"]),
)
def jwt_decode(payload: JwtRequest) -> dict[str, Any]:
    parts = payload.token.strip().split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=422, detail="jwt_must_have_three_segments")
    try:
        header = json.loads(b64url_decode(parts[0]).decode("utf-8"))
        claims = json.loads(b64url_decode(parts[1]).decode("utf-8"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail="jwt_header_or_payload_is_not_valid_json") from exc
    return {
        "header": header,
        "payload": claims,
        "signature_present": bool(parts[2]),
        "verified": False,
        "warning": "Decoded only; signature and claims are not verified.",
    }


@app.post(
    "/v1/json/canonicalize",
    tags=["json", "canonicalize", "hashing", "signing"],
    summary="Canonicalize JSON",
    description="Serialize JSON with sorted keys and compact separators.",
    openapi_extra=_openapi_extra(MICRO_PRICE, TOOL_SPECS[10]["buyer_queries"]),
)
def json_canonicalize(payload: JsonCanonicalizeRequest) -> dict[str, Any]:
    try:
        canonical = json.dumps(payload.value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="value_is_not_canonicalizable_json") from exc
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {"canonical": canonical, "sha256": digest}


def register_agent402_later() -> None:
    if not AGENT402_REGISTER:
        return
    time.sleep(15)
    try:
        response = requests.post(
            "https://agent402.tools/api/index/register",
            json={"origin": PUBLIC_ORIGIN},
            timeout=20,
            headers={"user-agent": "capi2-agent-utilities/2.0.0"},
        )
        body = response.json() if "application/json" in response.headers.get("content-type", "") else {"text": response.text[:500]}
        print(f"agent402 registration: status={response.status_code} listed={body.get('listed')} seller={body.get('seller')}")
    except Exception as exc:
        print(f"agent402 registration deferred: {exc.__class__.__name__}: {exc}")


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=register_agent402_later, daemon=True).start()
