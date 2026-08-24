"""Same-origin intelligence storefront for the already-listed Claim Verify seller.

Agent402's public new-origin queue can be full.  This module avoids depending on
another seller slot by publishing the five intelligence products under the
existing, routable capi2 Claim Verify origin.  It patches only that FastAPI app,
adds the paid route configurations before x402 middleware is installed, and
keeps all target fetching public-network-only.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import ipaddress
import json
import os
import re
import socket
import ssl
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

PUBLIC_ORIGIN = os.getenv(
    "CAPI2_CLAIM_VERIFY_ORIGIN",
    "https://capi2-claim-verify.onrender.com",
).rstrip("/")
PAY_TO = os.getenv(
    "CAPI2_PAY_TO",
    "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a",
)
NETWORK = os.getenv("CAPI2_X402_NETWORK", "eip155:8453")
PRICE = os.getenv("CAPI2_STOREFRONT_INTELLIGENCE_PRICE", "$0.005")
MAX_FETCH_BYTES = int(os.getenv("CAPI2_INTELLIGENCE_MAX_FETCH_BYTES", "750000"))
MAX_REDIRECTS = 3
USER_AGENT = "capi2-unified-storefront/1.0 (+x402; public-data-only)"

TEXT_URL_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "format": "uri",
            "description": "Public HTTP(S) URL.",
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}
WEB_LOOKUP_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "format": "uri",
            "description": "Public HTTP(S) URL to fetch live.",
        },
        "query": {
            "type": ["string", "null"],
            "maxLength": 500,
            "description": "Optional terms used to rank matching passages.",
        },
        "max_bytes": {
            "type": "integer",
            "minimum": 1000,
            "maximum": MAX_FETCH_BYTES,
            "default": 200000,
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}
DOMAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {
            "type": "string",
            "description": "Public DNS domain, for example example.com.",
        },
        "include_rdap": {"type": "boolean", "default": True},
    },
    "required": ["domain"],
    "additionalProperties": False,
}
EVIDENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "format": "uri",
            "description": "Public source URL.",
        },
        "query": {
            "type": "string",
            "minLength": 2,
            "maxLength": 1000,
            "description": "Claim, question, or evidence terms.",
        },
        "max_passages": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "default": 5,
        },
    },
    "required": ["url", "query"],
    "additionalProperties": False,
}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "path": "/v1/web/lookup",
        "name": "capi2 Live Web Lookup",
        "summary": "Fetch a live public webpage or API and return structured data or relevant passages.",
        "description": "Current public HTTP(S) lookup for autonomous agents; no signup or API key.",
        "tags": ["web lookup", "live data", "public api", "research", "x402"],
        "buyer_queries": [
            "fetch a live public URL",
            "look up current public API data",
            "read a webpage for an agent",
            "retrieve live web evidence",
        ],
        "schema": WEB_LOOKUP_SCHEMA,
        "example": {"url": "https://example.com", "query": "example domain"},
        "output": {
            "status": 200,
            "content_type": "text/html",
            "title": "Example Domain",
            "passages": [{"text": "Example Domain", "score": 1.0}],
        },
    },
    {
        "path": "/v1/domain/intelligence",
        "name": "capi2 Domain Intelligence",
        "summary": "Return DNS, HTTPS, TLS, and optional RDAP facts for a public domain.",
        "description": "Public domain intelligence for vendor checks, routing, and security triage.",
        "tags": ["domain intelligence", "dns", "rdap", "tls", "vendor risk"],
        "buyer_queries": [
            "inspect domain dns records",
            "check registrar and domain age",
            "check tls certificate and https",
            "vendor domain due diligence",
        ],
        "schema": DOMAIN_SCHEMA,
        "example": {"domain": "example.com", "include_rdap": True},
        "output": {
            "domain": "example.com",
            "dns": {"A": {"answers": ["93.184.216.34"]}},
            "https": {"reachable": True, "status": 200},
            "tls": {"available": True},
        },
    },
    {
        "path": "/v1/api/audit",
        "name": "capi2 API Discovery Audit",
        "summary": "Audit OpenAPI, x402, agent manifests, robots, llms, and health surfaces.",
        "description": "Machine-readable readiness audit for public APIs and autonomous-agent sellers.",
        "tags": ["api audit", "openapi", "agent discovery", "endpoint audit", "x402"],
        "buyer_queries": [
            "audit an api endpoint",
            "check openapi and agent manifests",
            "inspect api discovery readiness",
            "vendor api due diligence",
        ],
        "schema": TEXT_URL_SCHEMA,
        "example": {"url": "https://api.example.com/v1/tool"},
        "output": {
            "origin": "https://api.example.com",
            "score": 85,
            "grade": "A",
            "openapi": {"present": True},
            "x402": {"present": True},
        },
    },
    {
        "path": "/v1/evidence/extract",
        "name": "capi2 Evidence Extract",
        "summary": "Extract and rank passages from a supplied public source for a claim or question.",
        "description": "Public-source evidence extraction without making a consequential decision.",
        "tags": ["evidence extraction", "web research", "fact checking", "source analysis", "x402"],
        "buyer_queries": [
            "extract evidence from webpage",
            "find passages supporting a claim",
            "source evidence for due diligence",
            "webpage fact checking",
        ],
        "schema": EVIDENCE_SCHEMA,
        "example": {
            "url": "https://example.com",
            "query": "example domain",
            "max_passages": 5,
        },
        "output": {
            "source_url": "https://example.com",
            "passages": [{"text": "Example Domain", "score": 1.0}],
            "passage_count": 1,
        },
    },
    {
        "path": "/v1/x402/health",
        "name": "capi2 Agent x402 Health",
        "summary": "Check public seller discovery and x402 operational readiness without paying it.",
        "description": "Non-payment health and discovery audit for public x402 sellers and agents.",
        "tags": ["x402 health", "agent health", "payment api", "seller monitoring", "audit"],
        "buyer_queries": [
            "check x402 endpoint health",
            "is this agent seller discoverable",
            "audit x402 manifests and openapi",
            "monitor paid agent api health",
        ],
        "schema": TEXT_URL_SCHEMA,
        "example": {"url": "https://seller.example.com/v1/tool"},
        "output": {
            "status": "healthy",
            "score": 95,
            "x402_manifest": True,
            "resource_match": True,
            "payments_attempted": False,
        },
    },
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _price_usd() -> float:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", PRICE)
    return float(match.group(1)) if match else 0.005


def _validate_public_url(url: str) -> None:
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url_must_be_public_http_or_https")
    if parsed.username or parsed.password:
        raise ValueError("embedded_credentials_not_allowed")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".local"):
        raise ValueError("private_hostname_blocked")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        resolved = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("dns_resolution_failed") from exc
    if not resolved:
        raise ValueError("dns_resolution_failed")
    for entry in resolved:
        ip = ipaddress.ip_address(entry[4][0])
        if not ip.is_global:
            raise ValueError("private_or_reserved_ip_blocked")


def _safe_fetch(url: str, *, max_bytes: int = 200000) -> dict[str, Any]:
    current = str(url)
    for _ in range(MAX_REDIRECTS + 1):
        _validate_public_url(current)
        try:
            response = requests.get(
                current,
                timeout=(4, 12),
                allow_redirects=False,
                stream=True,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json,text/html,text/plain,*/*;q=0.5",
                },
            )
        except requests.RequestException as exc:
            raise ValueError(f"upstream_fetch_failed:{exc.__class__.__name__}") from exc

        if 300 <= response.status_code < 400:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise ValueError("redirect_without_location")
            current = urljoin(current, location)
            continue

        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            response.close()
            raise ValueError("upstream_response_too_large")

        raw = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                raw.extend(chunk)
                if len(raw) > max_bytes:
                    raise ValueError("upstream_response_too_large")
        finally:
            response.close()

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        encoding = response.encoding or "utf-8"
        return {
            "requested_url": str(url),
            "final_url": current,
            "status": response.status_code,
            "content_type": content_type,
            "headers": {
                key.lower(): value
                for key, value in response.headers.items()
                if key.lower() in {
                    "content-type",
                    "etag",
                    "last-modified",
                    "cache-control",
                    "server",
                }
            },
            "raw": bytes(raw),
            "text": bytes(raw).decode(encoding, errors="replace"),
        }
    raise ValueError("too_many_redirects")


def _html_to_text(value: str) -> str:
    cleaned = re.sub(
        r"(?is)<(script|style|noscript|svg|template)\b.*?>.*?</\1>",
        " ",
        value,
    )
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", cleaned)
    cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
    cleaned = html_lib.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _title_from_html(value: str) -> str | None:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", value)
    if not match:
        return None
    title = re.sub(r"\s+", " ", html_lib.unescape(match.group(1))).strip()
    return title[:300] or None


def _terms(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value).lower())
        if len(token) >= 3
    }


def _rank_passages(text: str, query: str, limit: int) -> list[dict[str, Any]]:
    query_terms = _terms(query)
    if not query_terms:
        return []
    chunks = [
        chunk.strip()
        for chunk in re.split(r"(?<=[.!?])\s+|\n+", text)
        if len(chunk.strip()) >= 20
    ]
    ranked: list[tuple[float, str]] = []
    for chunk in chunks:
        chunk_terms = _terms(chunk)
        overlap = len(query_terms & chunk_terms)
        if not overlap:
            continue
        coverage = overlap / max(len(query_terms), 1)
        density = overlap / max(len(chunk_terms), 1)
        score = round(min(1.0, coverage * 0.8 + density * 0.2), 4)
        ranked.append((score, chunk[:700]))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [{"text": text_value, "score": score} for score, text_value in ranked[:limit]]


def _normalise_domain(value: str) -> str:
    domain = str(value).strip().rstrip(".").lower()
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("invalid_domain") from exc
    if len(domain) > 253 or "." not in domain:
        raise ValueError("invalid_domain")
    labels = domain.split(".")
    if any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise ValueError("invalid_domain")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return domain
    raise ValueError("domain_name_required_not_ip")


def _dns_lookup(domain: str, record_type: str) -> dict[str, Any]:
    try:
        response = requests.get(
            "https://dns.google/resolve",
            params={"name": domain, "type": record_type},
            timeout=(4, 8),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        data = response.json()
    except Exception as exc:
        return {"status": "error", "error": exc.__class__.__name__, "answers": []}
    answers = []
    for answer in data.get("Answer", [])[:30]:
        if isinstance(answer, dict):
            answers.append(
                {
                    "type": answer.get("type"),
                    "ttl": answer.get("TTL"),
                    "data": answer.get("data"),
                }
            )
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
                    "subject": dict(item[0] for item in cert.get("subject", [])),
                    "issuer": dict(item[0] for item in cert.get("issuer", [])),
                    "not_before": cert.get("notBefore"),
                    "not_after": cert.get("notAfter"),
                    "subject_alt_names": [
                        value
                        for kind, value in cert.get("subjectAltName", [])
                        if kind == "DNS"
                    ][:20],
                }
    except Exception as exc:
        return {"available": False, "error": exc.__class__.__name__}


def _rdap_summary(domain: str) -> dict[str, Any]:
    try:
        fetched = _safe_fetch(
            f"https://rdap.org/domain/{domain}",
            max_bytes=500000,
        )
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
        "nameservers": [
            item.get("ldhName")
            for item in data.get("nameservers", [])
            if isinstance(item, dict)
        ][:20],
    }


def _origin_from_url(value: str) -> tuple[str, str]:
    _validate_public_url(value)
    parsed = urlparse(str(value))
    return f"{parsed.scheme}://{parsed.netloc}", parsed.path or "/"


def _surface(origin: str, path: str, max_bytes: int = 250000) -> dict[str, Any]:
    url = f"{origin}{path}"
    try:
        result = _safe_fetch(url, max_bytes=max_bytes)
        parsed_json = None
        if (
            result["content_type"] in {"application/json", "application/problem+json"}
            or result["text"].lstrip().startswith(("{", "["))
        ):
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
    except Exception as exc:
        return {"url": url, "present": False, "error": str(exc)[:200]}


def _audit_discovery(url: str) -> dict[str, Any]:
    origin, target_path = _origin_from_url(url)
    surfaces = {
        "root": _surface(origin, "/", 80000),
        "openapi": _surface(origin, "/openapi.json", 500000),
        "x402": _surface(origin, "/.well-known/x402", 350000),
        "agent": _surface(origin, "/.well-known/agent.json", 350000),
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
                operation = path_item.get(method)
                if isinstance(operation, dict):
                    operations += 1
                    if (
                        operation.get("x-payment-info")
                        or operation.get("x-x402-price")
                        or operation.get("x-price")
                    ):
                        paid_operations += 1

    resources: list[dict[str, Any]] = []
    if isinstance(x402_data, dict):
        raw_resources = x402_data.get("resources")
        if isinstance(raw_resources, list):
            resources = [item for item in raw_resources if isinstance(item, dict)]

    target_url = f"{origin}{target_path}"
    resource_match = any(
        str(item.get("resource", "")).rstrip("/") == target_url.rstrip("/")
        or str(item.get("endpoint", "")).endswith(target_path)
        for item in resources
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
    for key, label in (
        ("openapi", "publish /openapi.json"),
        ("x402", "publish /.well-known/x402"),
        ("agent", "publish /.well-known/agent.json"),
        ("robots", "publish /robots.txt"),
        ("llms", "publish /llms.txt"),
    ):
        if not surfaces[key].get("present"):
            recommendations.append(label)
    if isinstance(openapi_data, dict) and resources and not paid_operations:
        recommendations.append("add explicit x402 pricing metadata to paid OpenAPI operations")
    if resources and target_path != "/" and not resource_match:
        recommendations.append("list the target paid resource in /.well-known/x402")

    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D"
    return {
        "checked_at": _utc_now(),
        "target_url": str(url),
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
        "surfaces": {
            key: {inner_key: inner_value for inner_key, inner_value in value.items() if inner_key != "json"}
            for key, value in surfaces.items()
        },
        "recommendations": recommendations,
    }


def _bazaar_extension(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "bazaar": {
            "info": {
                "input": {
                    "type": "http",
                    "method": "POST",
                    "bodyType": "json",
                    "body": spec["example"],
                },
                "output": {"type": "json", "example": spec["output"]},
            },
            "schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "input": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "const": "http"},
                            "method": {"type": "string", "const": "POST"},
                            "bodyType": {"type": "string", "const": "json"},
                            "body": spec["schema"],
                        },
                        "required": ["type", "method", "bodyType", "body"],
                        "additionalProperties": False,
                    },
                    "output": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "example": {"type": "object"},
                        },
                        "required": ["type"],
                    },
                },
                "required": ["input"],
            },
        }
    }


def _openapi_extra(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "x-price": PRICE,
        "x-x402-price": PRICE,
        "x-x402-network": NETWORK,
        "x-buyer-intents": spec["buyer_queries"],
        "x-bazaar-discoverable": True,
        "responses": {
            "402": {
                "description": "Payment Required; retry with a valid x402 PAYMENT-SIGNATURE.",
            }
        },
    }


def _catalog() -> dict[str, Any]:
    return {
        "name": "capi2 Unified Intelligence Storefront",
        "origin": PUBLIC_ORIGIN,
        "asset": "USDC",
        "network": NETWORK,
        "price": PRICE,
        "pay_to": PAY_TO,
        "seller_slot_strategy": "same-origin products under the existing Agent402-listed Claim Verify seller",
        "tools": [
            {
                "name": spec["name"],
                "service_name": spec["name"],
                "method": "POST",
                "path": spec["path"],
                "resource": f"{PUBLIC_ORIGIN}{spec['path']}",
                "price": PRICE,
                "price_usd": _price_usd(),
                "summary": spec["summary"],
                "tags": spec["tags"],
                "buyer_queries": spec["buyer_queries"],
                "input_schema": spec["schema"],
                "example_request": spec["example"],
            }
            for spec in TOOL_SPECS
        ],
    }


def _install() -> None:
    try:
        from fastapi import FastAPI, HTTPException
        from pydantic import BaseModel, Field, HttpUrl
    except Exception:
        return

    class WebLookupRequest(BaseModel):
        url: HttpUrl
        query: str | None = Field(default=None, max_length=500)
        max_bytes: int = Field(default=200000, ge=1000, le=MAX_FETCH_BYTES)

    class DomainRequest(BaseModel):
        domain: str = Field(min_length=1, max_length=253)
        include_rdap: bool = True

    class UrlAuditRequest(BaseModel):
        url: HttpUrl

    class EvidenceRequest(BaseModel):
        url: HttpUrl
        query: str = Field(min_length=2, max_length=1000)
        max_passages: int = Field(default=5, ge=1, le=10)

    original_middleware = FastAPI.add_middleware
    if not getattr(original_middleware, "_capi2_storefront_payment_routes", False):
        def patched_middleware(self, middleware_class, *args, **kwargs):
            if "Claim Verify" in str(getattr(self, "title", "")):
                routes = kwargs.get("routes")
                if isinstance(routes, dict):
                    try:
                        from x402.http import PaymentOption
                        from x402.http.types import RouteConfig

                        for spec in TOOL_SPECS:
                            routes.setdefault(
                                f"POST {spec['path']}",
                                RouteConfig(
                                    accepts=[
                                        PaymentOption(
                                            scheme="exact",
                                            pay_to=PAY_TO,
                                            price=PRICE,
                                            network=NETWORK,
                                        )
                                    ],
                                    resource=f"{PUBLIC_ORIGIN}{spec['path']}",
                                    mime_type="application/json",
                                    description=spec["description"],
                                    service_name=spec["name"],
                                    tags=spec["tags"],
                                    extensions=_bazaar_extension(spec),
                                ),
                            )
                        print(
                            f"claim-storefront: payment routes configured count={len(TOOL_SPECS)} price={PRICE}",
                            flush=True,
                        )
                    except Exception as exc:
                        print(
                            f"claim-storefront: payment route error {type(exc).__name__}: {exc}",
                            flush=True,
                        )
            return original_middleware(self, middleware_class, *args, **kwargs)

        patched_middleware._capi2_storefront_payment_routes = True
        FastAPI.add_middleware = patched_middleware

    original_init = FastAPI.__init__
    if getattr(original_init, "_capi2_unified_storefront", False):
        return

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        if "Claim Verify" not in str(getattr(self, "title", "")):
            return

        async def storefront():
            return _catalog()

        async def web_lookup(payload: WebLookupRequest):
            try:
                fetched = _safe_fetch(str(payload.url), max_bytes=payload.max_bytes)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            content_type = fetched["content_type"]
            body_text = fetched["text"]
            parsed_json = None
            if (
                content_type in {"application/json", "application/problem+json"}
                or body_text.lstrip().startswith(("{", "["))
            ):
                try:
                    parsed_json = json.loads(body_text)
                except Exception:
                    parsed_json = None
            if "html" in content_type or "<html" in body_text[:500].lower():
                title = _title_from_html(body_text)
                clean_text = _html_to_text(body_text)
            else:
                title = None
                clean_text = body_text.strip()
            return {
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
                "passages": _rank_passages(clean_text, payload.query, 5)
                if payload.query
                else [],
            }

        async def domain_intelligence(payload: DomainRequest):
            try:
                domain = _normalise_domain(payload.domain)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            dns = {
                record: _dns_lookup(domain, record)
                for record in ("A", "AAAA", "MX", "NS", "TXT", "CAA")
            }
            try:
                https = _safe_fetch(f"https://{domain}/", max_bytes=80000)
                https_summary = {
                    "reachable": True,
                    "status": https["status"],
                    "final_url": https["final_url"],
                    "content_type": https["content_type"],
                    "server": https["headers"].get("server"),
                    "title": _title_from_html(https["text"])
                    if "html" in https["content_type"]
                    else None,
                }
            except Exception as exc:
                https_summary = {"reachable": False, "error": str(exc)[:200]}
            return {
                "checked_at": _utc_now(),
                "domain": domain,
                "dns": dns,
                "https": https_summary,
                "tls": _tls_info(domain),
                "rdap": _rdap_summary(domain)
                if payload.include_rdap
                else {"skipped": True},
                "note": "Public technical and registration metadata only.",
            }

        async def api_audit(payload: UrlAuditRequest):
            try:
                result = _audit_discovery(str(payload.url))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            result["audit_type"] = "api_discovery"
            return result

        async def evidence_extract(payload: EvidenceRequest):
            try:
                fetched = _safe_fetch(str(payload.url), max_bytes=MAX_FETCH_BYTES)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            body = fetched["text"]
            if "html" in fetched["content_type"] or "<html" in body[:500].lower():
                title = _title_from_html(body)
                clean_text = _html_to_text(body)
            else:
                title = None
                clean_text = body.strip()
            passages = _rank_passages(clean_text, payload.query, payload.max_passages)
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
                "caveat": "Lexical relevance is not proof that a claim is true.",
            }

        async def x402_health(payload: UrlAuditRequest):
            try:
                audit = _audit_discovery(str(payload.url))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
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

        self.add_api_route(
            "/v1/storefront",
            storefront,
            methods=["GET"],
            tags=["discovery", "catalog", "x402"],
            summary="Unified same-origin paid intelligence catalog",
            description=(
                "Free machine-readable catalog for the five $0.005 intelligence "
                "products published under this already-listed Agent402 seller."
            ),
        )

        handlers = [
            (TOOL_SPECS[0], web_lookup),
            (TOOL_SPECS[1], domain_intelligence),
            (TOOL_SPECS[2], api_audit),
            (TOOL_SPECS[3], evidence_extract),
            (TOOL_SPECS[4], x402_health),
        ]
        for spec, handler in handlers:
            self.add_api_route(
                spec["path"],
                handler,
                methods=["POST"],
                tags=spec["tags"],
                summary=spec["summary"],
                description=spec["description"],
                openapi_extra=_openapi_extra(spec),
            )

        print(
            f"claim-storefront: installed tools={len(TOOL_SPECS)} price={PRICE} origin={PUBLIC_ORIGIN}",
            flush=True,
        )

    patched_init._capi2_unified_storefront = True
    FastAPI.__init__ = patched_init


_install()
