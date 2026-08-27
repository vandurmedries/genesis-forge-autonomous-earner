from __future__ import annotations

import html as html_lib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

from capi2.demand_tools.app import (
    _dns_lookup,
    _normalize_domain,
    _rdap_summary,
    _safe_fetch,
    _title_from_html,
    _tls_info,
)

PUBLIC_ORIGIN = os.getenv(
    "CAPI2_PREMIUM_DOMAIN_ORIGIN",
    "https://capi2-company-domain-intel.onrender.com",
).rstrip("/")
PAY_TO = os.getenv("CAPI2_PAY_TO", "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a")
NETWORK = os.getenv("CAPI2_X402_NETWORK", "eip155:8453")
FACILITATOR_URL = os.getenv("CAPI2_X402_FACILITATOR", "https://facilitator.xpay.sh")
PRICE = os.getenv("CAPI2_COMPANY_DOMAIN_PRICE", "$0.05")
AGENT402_REGISTER = os.getenv("CAPI2_AGENT402_REGISTER", "true").lower() == "true"

app = FastAPI(
    title="capi2 Company & Domain Intelligence Pack",
    version="1.0.0",
    description=(
        "One paid x402 call for public company/domain due diligence: DNS, mail security, RDAP, "
        "HTTPS/TLS, website identity and lightweight technology signals."
    ),
)

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
server = x402ResourceServer(facilitator)
server.register(NETWORK, ExactEvmServerScheme())

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {
            "type": "string",
            "description": "Public DNS domain, for example example.com.",
        },
        "company_name": {
            "type": ["string", "null"],
            "maxLength": 200,
            "description": "Optional expected company/brand name for identity matching.",
        },
    },
    "required": ["domain"],
}

OUTPUT_EXAMPLE = {
    "domain": "example.com",
    "company": {"observed_name": "Example Domain", "expected_name": None, "name_match": None},
    "website": {"reachable": True, "status": 200, "https": True},
    "dns": {"A": [], "AAAA": [], "MX": [], "NS": [], "TXT": [], "CAA": []},
    "mail_security": {"spf": {"present": False}, "dmarc": {"present": False}},
    "tls": {"available": True},
    "rdap": {"available": True},
    "technology": {"signals": []},
    "technical_posture": {"score": 70, "grade": "B", "signals": []},
}

BAZAAR_EXTENSION = {
    "bazaar": {
        "info": {
            "input": {
                "type": "http",
                "method": "POST",
                "bodyType": "json",
                "body": {"domain": "example.com", "company_name": None},
            },
            "output": {"type": "json", "example": OUTPUT_EXAMPLE},
        },
        "schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "input": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "const": "http"},
                        "method": {"type": "string", "enum": ["POST"]},
                        "bodyType": {"type": "string", "const": "json"},
                        "body": INPUT_SCHEMA,
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

RESOURCE_PATH = "/v1/company/domain-intelligence"
RESOURCE_URL = f"{PUBLIC_ORIGIN}{RESOURCE_PATH}"

routes = {
    f"POST {RESOURCE_PATH}": RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                pay_to=PAY_TO,
                price=PRICE,
                network=NETWORK,
            )
        ],
        resource=RESOURCE_URL,
        mime_type="application/json",
        description=(
            "Complete public company/domain intelligence pack: DNS, SPF/DMARC, RDAP, HTTPS/TLS, "
            "website identity, technology signals and a transparent technical-posture score."
        ),
        service_name="capi2 Company & Domain Intelligence Pack",
        tags=[
            "company intelligence",
            "domain intelligence",
            "dns",
            "rdap",
            "tls",
            "email security",
            "vendor due diligence",
            "b2b enrichment",
        ],
        extensions=BAZAAR_EXTENSION,
    )
}
app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


class DomainPackRequest(BaseModel):
    domain: str = Field(min_length=3, max_length=253)
    company_name: Optional[str] = Field(default=None, max_length=200)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump(mode="json"))
    if hasattr(value, "dict"):
        return _plain(value.dict())
    return str(value)


def _deep_first(value: Any, *keys: str) -> Any:
    if isinstance(value, dict):
        for key in keys:
            if value.get(key) not in (None, ""):
                return value[key]
        for nested in value.values():
            found = _deep_first(nested, *keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _deep_first(nested, *keys)
            if found not in (None, ""):
                return found
    return None


def _log_settlement(ctx: Any) -> None:
    try:
        requirements = _plain(getattr(ctx, "requirements", None)) or {}
        result = _plain(getattr(ctx, "result", None)) or {}
        payload = _plain(getattr(ctx, "payment_payload", None)) or {}
        event = {
            "success": bool(result.get("success", True)),
            "path": RESOURCE_PATH,
            "resource": requirements.get("resource") or payload.get("resource") or RESOURCE_URL,
            "amount_usdc": requirements.get("price") or requirements.get("amount") or PRICE,
            "transaction": result.get("transaction") or result.get("transaction_hash") or result.get("txHash"),
            "network": requirements.get("network") or payload.get("network") or NETWORK,
            "payer": _deep_first(result, "payer", "from", "sender") or _deep_first(payload, "payer", "from", "sender"),
            "timestamp": _now(),
        }
        print("capi2-settlement:" + json.dumps(event, sort_keys=True, default=str), flush=True)
    except Exception as exc:
        print(f"capi2-settlement: observer_error={exc.__class__.__name__}", flush=True)


server.on_after_settle(_log_settlement)


def _meta(html: str, key: str) -> Optional[str]:
    patterns = [
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\']{re.escape(key)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            return html_lib.unescape(match.group(1)).strip()[:500] or None
    return None


def _website_profile(domain: str) -> dict[str, Any]:
    try:
        fetched = _safe_fetch(f"https://{domain}/", max_bytes=300000)
    except HTTPException as exc:
        return {"reachable": False, "https": True, "error": str(exc.detail)}

    body = fetched["text"]
    title = _title_from_html(body) if "html" in fetched["content_type"] else None
    description = _meta(body, "description") or _meta(body, "og:description")
    og_site = _meta(body, "og:site_name")
    generator = _meta(body, "generator")
    lower = body.lower()
    headers = fetched.get("headers", {})
    server_header = headers.get("server")

    tech: list[str] = []
    checks = [
        ("wordpress", "wp-content" in lower or "wp-includes" in lower),
        ("shopify", "cdn.shopify.com" in lower or "shopify" in lower),
        ("next.js", "__next_data__" in lower or "/_next/" in lower),
        ("react", "react" in lower and ("root" in lower or "__next" in lower)),
        ("cloudflare", bool(server_header and "cloudflare" in server_header.lower())),
        ("nginx", bool(server_header and "nginx" in server_header.lower())),
        ("apache", bool(server_header and "apache" in server_header.lower())),
    ]
    tech.extend(name for name, present in checks if present)
    if generator:
        tech.append(f"generator:{generator}")

    return {
        "reachable": True,
        "https": fetched["final_url"].startswith("https://"),
        "status": fetched["status"],
        "final_url": fetched["final_url"],
        "content_type": fetched["content_type"],
        "title": title,
        "description": description,
        "site_name": og_site,
        "server": server_header,
        "technology_signals": sorted(set(tech)),
        "security_headers": {
            "hsts": "strict-transport-security" in headers,
            "csp": "content-security-policy" in headers,
        },
    }


def _txt_values(record: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for answer in record.get("answers", []) if isinstance(record, dict) else []:
        value = answer.get("data") if isinstance(answer, dict) else None
        if isinstance(value, str):
            out.append(value.strip('"'))
    return out


def _mail_security(domain: str, txt_record: dict[str, Any]) -> dict[str, Any]:
    root_txt = _txt_values(txt_record)
    spf_values = [value for value in root_txt if value.lower().startswith("v=spf1")]
    dmarc_record = _dns_lookup(f"_dmarc.{domain}", "TXT")
    dmarc_values = [value for value in _txt_values(dmarc_record) if value.lower().startswith("v=dmarc1")]
    dmarc_policy = None
    if dmarc_values:
        match = re.search(r"(?:^|;)\s*p=([^;\s]+)", dmarc_values[0], re.I)
        dmarc_policy = match.group(1).lower() if match else None
    return {
        "spf": {"present": bool(spf_values), "records": spf_values[:5]},
        "dmarc": {
            "present": bool(dmarc_values),
            "policy": dmarc_policy,
            "records": dmarc_values[:5],
        },
    }


def _name_match(expected: Optional[str], *observed: Optional[str]) -> Optional[float]:
    if not expected:
        return None
    wanted = {x for x in re.findall(r"[a-z0-9]+", expected.lower()) if len(x) >= 2}
    seen = {
        x
        for value in observed
        if value
        for x in re.findall(r"[a-z0-9]+", value.lower())
        if len(x) >= 2
    }
    if not wanted:
        return None
    return round(len(wanted & seen) / len(wanted), 3)


def _posture(website: dict[str, Any], dns: dict[str, Any], mail: dict[str, Any], tls: dict[str, Any], rdap: dict[str, Any]) -> dict[str, Any]:
    score = 0
    signals: list[dict[str, Any]] = []

    def add(points: int, key: str, ok: bool, note: str) -> None:
        nonlocal score
        if ok:
            score += points
        signals.append({"signal": key, "ok": ok, "points": points if ok else 0, "note": note})

    add(15, "website_reachable", bool(website.get("reachable")), "Public HTTPS website responds.")
    add(10, "https", bool(website.get("https")), "Website resolves over HTTPS.")
    add(15, "tls", bool(tls.get("available")), "TLS handshake and certificate are available.")
    add(10, "rdap", bool(rdap.get("available")), "RDAP registration metadata is available.")
    add(10, "mx", bool(dns.get("MX", {}).get("answers")), "MX records are published.")
    add(15, "spf", bool(mail.get("spf", {}).get("present")), "SPF record is published.")
    add(15, "dmarc", bool(mail.get("dmarc", {}).get("present")), "DMARC record is published.")
    add(5, "hsts", bool(website.get("security_headers", {}).get("hsts")), "HSTS header is present.")
    add(5, "csp", bool(website.get("security_headers", {}).get("csp")), "CSP header is present.")

    grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "D"
    return {
        "score": score,
        "grade": grade,
        "signals": signals,
        "meaning": "Transparent public technical-posture score; not a credit, compliance, security certification, or consequential decision.",
    }


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "capi2 Company & Domain Intelligence Pack",
        "paid": True,
        "price": PRICE,
        "asset": "USDC",
        "network": NETWORK,
        "resource": RESOURCE_URL,
        "input_example": {"domain": "example.com", "company_name": None},
        "discover": {
            "x402": f"{PUBLIC_ORIGIN}/.well-known/x402",
            "agent": f"{PUBLIC_ORIGIN}/.well-known/agent.json",
            "openapi": f"{PUBLIC_ORIGIN}/openapi.json",
            "llms": f"{PUBLIC_ORIGIN}/llms.txt",
        },
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "capi2-company-domain-intel",
        "version": "1.0.0",
        "price": PRICE,
        "network": NETWORK,
        "asset": "USDC",
        "facilitator": FACILITATOR_URL,
    }


@app.get("/.well-known/x402")
def x402_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Company & Domain Intelligence Pack",
        "protocol": "x402",
        "network": NETWORK,
        "asset": "USDC",
        "payTo": PAY_TO,
        "resources": [
            {
                "name": "capi2 Company & Domain Intelligence Pack",
                "service_name": "capi2 Company & Domain Intelligence Pack",
                "resource": RESOURCE_URL,
                "endpoint": f"POST {RESOURCE_PATH}",
                "method": "POST",
                "price": PRICE,
                "price_usd": 0.05,
                "summary": "One-call public company/domain due-diligence and technical intelligence pack.",
                "tags": ["company intelligence", "domain intelligence", "b2b enrichment", "vendor due diligence", "dns", "tls", "rdap", "email security"],
                "buyer_queries": [
                    "research a company domain",
                    "domain due diligence",
                    "vendor domain intelligence",
                    "b2b company enrichment",
                    "dns rdap tls mail security report",
                ],
                "example_request": {"domain": "example.com", "company_name": None},
                "input_schema": INPUT_SCHEMA,
            }
        ],
    }


@app.get("/.well-known/agent.json")
def agent_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Company & Domain Intelligence Pack",
        "protocol": "capi2.company-domain/1.0",
        "description": "Single paid public-data intelligence pack for company/domain research and vendor due diligence.",
        "payment": {"protocol": "x402", "network": NETWORK, "asset": "USDC", "payTo": PAY_TO},
        "tools": x402_manifest()["resources"],
    }


@app.get("/llms.txt", response_class=PlainTextResponse)
def llms() -> str:
    return (
        "# capi2 Company & Domain Intelligence Pack\n\n"
        f"POST {RESOURCE_URL}\n"
        f"Price: {PRICE} USDC on {NETWORK}\n"
        "Input: {domain, optional company_name}\n"
        "Output: DNS, MX/TXT/CAA, SPF, DMARC, RDAP, HTTPS/TLS, website identity, technology signals and a transparent technical-posture score.\n"
    )


@app.post(
    RESOURCE_PATH,
    tags=["company intelligence", "domain intelligence", "vendor due diligence", "b2b enrichment"],
    summary="Company and domain intelligence pack",
    description="One paid call returning public DNS/RDAP/TLS/mail-security/website and company-domain identity signals.",
    openapi_extra={
        "x-price": PRICE,
        "x-x402-price": PRICE,
        "x-x402-network": NETWORK,
        "x-buyer-intents": [
            "research company domain",
            "vendor due diligence",
            "company enrichment",
            "domain security posture",
        ],
        "x-bazaar-discoverable": True,
    },
)
def company_domain_intelligence(payload: DomainPackRequest) -> dict[str, Any]:
    domain = _normalize_domain(payload.domain)
    dns = {record: _dns_lookup(domain, record) for record in ("A", "AAAA", "MX", "NS", "TXT", "CAA")}
    website = _website_profile(domain)
    tls = _tls_info(domain)
    rdap = _rdap_summary(domain)
    mail = _mail_security(domain, dns["TXT"])

    observed_name = website.get("site_name") or website.get("title")
    match = _name_match(payload.company_name, observed_name, website.get("description"))
    posture = _posture(website, dns, mail, tls, rdap)

    return {
        "checked_at": _now(),
        "domain": domain,
        "company": {
            "expected_name": payload.company_name,
            "observed_name": observed_name,
            "name_match": match,
        },
        "website": website,
        "dns": dns,
        "mail_security": mail,
        "tls": tls,
        "rdap": rdap,
        "technology": {"signals": website.get("technology_signals", [])},
        "technical_posture": posture,
        "provenance": {
            "dns": "Google Public DNS JSON API",
            "rdap": "RDAP.org bootstrap/client endpoint",
            "website": f"https://{domain}/",
            "tls": f"TLS handshake to {domain}:443",
        },
        "caveat": "Public-data technical intelligence only; not a security certification, legal conclusion, credit decision, or private-data enrichment product.",
    }


def _register_agent402() -> None:
    if not AGENT402_REGISTER:
        return
    time.sleep(12)
    try:
        response = requests.post(
            "https://agent402.tools/api/index/register",
            json={"origin": PUBLIC_ORIGIN},
            timeout=20,
            headers={"user-agent": "capi2-company-domain-intel/1.0"},
        )
        body = response.json() if "application/json" in response.headers.get("content-type", "") else {"text": response.text[:500]}
        print(
            "agent402 registration: "
            f"status={response.status_code} listed={body.get('listed')} seller={body.get('seller')}",
            flush=True,
        )
    except Exception as exc:
        print(f"agent402 registration deferred: {exc.__class__.__name__}: {exc}", flush=True)


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=_register_agent402, daemon=True).start()
