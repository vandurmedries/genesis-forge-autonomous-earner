from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

from capi2.premium_domain.app import (
    BAZAAR_EXTENSION,
    INPUT_SCHEMA,
    _mail_security,
    _name_match,
    _posture,
    _website_profile,
)
from capi2.demand_tools.app import _dns_lookup, _normalize_domain, _rdap_summary, _tls_info

PUBLIC_ORIGIN = os.getenv("CAPI2_PREMIUM_DOMAIN_ORIGIN", "https://capi2-domain-pack.onrender.com").rstrip("/")
PAY_TO = os.getenv("CAPI2_PAY_TO", "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a")
NETWORK = os.getenv("CAPI2_X402_NETWORK", "eip155:8453")
FACILITATOR_URL = os.getenv("CAPI2_X402_FACILITATOR", "https://facilitator.xpay.sh")
PRICE = os.getenv("CAPI2_COMPANY_DOMAIN_PRICE", "$0.05")
RESOURCE_PATH = "/v1/company/domain-intelligence"
RESOURCE_URL = f"{PUBLIC_ORIGIN}{RESOURCE_PATH}"

app = FastAPI(
    title="capi2 Company & Domain Intelligence Pack",
    version="1.1.0",
    description="One-call paid public company/domain intelligence for agents and due-diligence workflows.",
)

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
server = x402ResourceServer(facilitator)
server.register(NETWORK, ExactEvmServerScheme())


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
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump(mode="json"))
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


def _settlement(ctx: Any) -> None:
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


server.on_after_settle(_settlement)


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "capi2 Company & Domain Intelligence Pack",
        "price": PRICE,
        "asset": "USDC",
        "network": NETWORK,
        "resource": RESOURCE_URL,
        "input_example": {"domain": "example.com", "company_name": "Example Domain"},
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "capi2-domain-pack",
        "version": "1.1.0",
        "price": PRICE,
        "asset": "USDC",
        "network": NETWORK,
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
        "resources": [{
            "name": "capi2 Company & Domain Intelligence Pack",
            "service_name": "capi2 Company & Domain Intelligence Pack",
            "resource": RESOURCE_URL,
            "endpoint": f"POST {RESOURCE_PATH}",
            "method": "POST",
            "price": PRICE,
            "price_usd": 0.05,
            "summary": "DNS, RDAP, TLS, mail-security, website identity and technology signals in one public-data call.",
            "tags": ["company intelligence", "domain intelligence", "b2b enrichment", "vendor due diligence", "dns", "rdap", "tls", "email security"],
            "buyer_queries": ["research company domain", "vendor domain due diligence", "b2b company enrichment", "dns rdap tls mail security report"],
            "example_request": {"domain": "example.com", "company_name": "Example Domain"},
            "input_schema": INPUT_SCHEMA,
        }],
    }


@app.get("/.well-known/agent.json")
def agent_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Company & Domain Intelligence Pack",
        "protocol": "capi2.company-domain/1.1",
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
        "Input: domain + optional company_name. Output: DNS, SPF/DMARC, RDAP, HTTPS/TLS, website identity, technology signals, transparent technical-posture score.\n"
    )


@app.post(
    RESOURCE_PATH,
    tags=["company intelligence", "domain intelligence", "vendor due diligence", "b2b enrichment"],
    summary="Company and domain intelligence pack",
    description="One paid public-data call returning DNS/RDAP/TLS/mail-security/website and company-domain identity signals.",
    openapi_extra={
        "x-price": PRICE,
        "x-x402-price": PRICE,
        "x-x402-network": NETWORK,
        "x-buyer-intents": ["research company domain", "vendor due diligence", "company enrichment", "domain technical posture"],
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
    return {
        "checked_at": _now(),
        "domain": domain,
        "company": {
            "expected_name": payload.company_name,
            "observed_name": observed_name,
            "name_match": _name_match(payload.company_name, observed_name, website.get("description")),
        },
        "website": website,
        "dns": dns,
        "mail_security": mail,
        "tls": tls,
        "rdap": rdap,
        "technology": {"signals": website.get("technology_signals", [])},
        "technical_posture": _posture(website, dns, mail, tls, rdap),
        "provenance": {
            "dns": "Google Public DNS JSON API",
            "rdap": "RDAP.org",
            "website": f"https://{domain}/",
            "tls": f"TLS handshake to {domain}:443",
        },
        "caveat": "Public-data technical intelligence only; not a security certification, legal conclusion, credit decision, or private-data enrichment product.",
    }


routes = {
    f"POST {RESOURCE_PATH}": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=PAY_TO, price=PRICE, network=NETWORK)],
        resource=RESOURCE_URL,
        mime_type="application/json",
        description="One-call company and domain public intelligence pack.",
        service_name="capi2 Company & Domain Intelligence Pack",
        tags=["company intelligence", "domain intelligence", "vendor due diligence", "b2b enrichment"],
        extensions=BAZAAR_EXTENSION,
    )
}
app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


def _register_agent402() -> None:
    time.sleep(15)
    try:
        response = requests.post(
            "https://agent402.tools/api/index/register",
            json={"origin": PUBLIC_ORIGIN},
            timeout=20,
            headers={"user-agent": "capi2-domain-pack/1.1"},
        )
        body = response.json() if "application/json" in response.headers.get("content-type", "") else {"text": response.text[:500]}
        print(f"agent402 registration: status={response.status_code} listed={body.get('listed')} seller={body.get('seller')}", flush=True)
    except Exception as exc:
        print(f"agent402 registration deferred: {exc.__class__.__name__}: {exc}", flush=True)


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=_register_agent402, daemon=True).start()
