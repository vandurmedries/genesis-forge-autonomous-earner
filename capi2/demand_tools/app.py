import base64
import hashlib
import json
import os
import re
import threading
import time
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

PAY_TO = os.getenv("CAPI2_PAY_TO", "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a")
NETWORK = os.getenv("CAPI2_X402_NETWORK", "eip155:8453")
FACILITATOR_URL = os.getenv("CAPI2_X402_FACILITATOR", "https://facilitator.payai.network")
MICRO_PRICE = os.getenv("CAPI2_DEMAND_TOOL_PRICE", "$0.001")
PUBLIC_ORIGIN = os.getenv("CAPI2_DEMAND_TOOLS_ORIGIN", "https://capi2-demand-tools.onrender.com").rstrip("/")
AGENT402_REGISTER = os.getenv("CAPI2_AGENT402_REGISTER", "true").lower() == "true"

app = FastAPI(
    title="capi2 Demand Microtools",
    version="1.1.0",
    description="Deterministic hashing, encoding, JWT inspection and canonical JSON utilities for agents that need stable machine-readable results.",
)

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
server = x402ResourceServer(facilitator)
server.register(NETWORK, ExactEvmServerScheme())


def paid(description: str) -> RouteConfig:
    return RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                pay_to=PAY_TO,
                price=MICRO_PRICE,
                network=NETWORK,
            )
        ],
        mime_type="application/json",
        description=description,
    )


routes = {
    "POST /v1/hash/sha256": paid("Generate a SHA-256 digest for text. Deterministic hashing utility for agents."),
    "POST /v1/hash/sha512": paid("Generate a SHA-512 digest for text. Deterministic hashing utility for agents."),
    "POST /v1/base64/encode": paid("Encode UTF-8 text as Base64 or URL-safe Base64."),
    "POST /v1/base64/decode": paid("Decode Base64 or URL-safe Base64 to UTF-8 text."),
    "POST /v1/jwt/decode": paid("Decode JWT header and payload without verifying the signature."),
    "POST /v1/json/canonicalize": paid("Canonicalize a JSON object using sorted keys and compact separators for stable hashing/signing inputs."),
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


def price_usd() -> float:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", MICRO_PRICE)
    return float(m.group(1)) if m else 0.001


def b64url_decode(segment: str) -> bytes:
    pad = "=" * ((4 - len(segment) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(segment + pad)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="invalid_base64url_segment") from exc


def tool_catalog() -> list[dict[str, Any]]:
    p = price_usd()
    return [
        {
            "name": "SHA-256 hash",
            "endpoint": "POST /v1/hash/sha256",
            "method": "POST",
            "price_usd": p,
            "summary": "SHA-256 hash / digest of UTF-8 text for integrity checks, cache keys, deduplication and agent workflows.",
        },
        {
            "name": "SHA-512 hash",
            "endpoint": "POST /v1/hash/sha512",
            "method": "POST",
            "price_usd": p,
            "summary": "SHA-512 hash / digest of UTF-8 text for integrity checks and deterministic agent workflows.",
        },
        {
            "name": "Base64 encode",
            "endpoint": "POST /v1/base64/encode",
            "method": "POST",
            "price_usd": p,
            "summary": "Encode text to Base64 or URL-safe Base64 for API payloads and agent interoperability.",
        },
        {
            "name": "Base64 decode",
            "endpoint": "POST /v1/base64/decode",
            "method": "POST",
            "price_usd": p,
            "summary": "Decode Base64 or URL-safe Base64 into UTF-8 text.",
        },
        {
            "name": "JWT decode",
            "endpoint": "POST /v1/jwt/decode",
            "method": "POST",
            "price_usd": p,
            "summary": "Decode JWT header and claims payload without signature verification; useful for token inspection and debugging.",
        },
        {
            "name": "JSON canonicalize",
            "endpoint": "POST /v1/json/canonicalize",
            "method": "POST",
            "price_usd": p,
            "summary": "Canonicalize JSON with sorted keys and compact separators for stable hashing, signatures and comparison.",
        },
    ]


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "capi2-demand-tools",
        "version": "1.1.0",
        "network": NETWORK,
        "asset": "USDC",
        "price_per_tool": MICRO_PRICE,
        "pay_to": PAY_TO,
        "paid_tools": len(tool_catalog()),
        "positioning": "high-demand deterministic x402 utility lane",
    }


@app.get("/", response_class=HTMLResponse)
def homepage() -> str:
    return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>capi2 Agent Utilities</title><style>body{margin:0;background:#101814;color:#eaf3ed;font:16px/1.55 system-ui,sans-serif}.w{max-width:920px;margin:auto;padding:40px}.hero{padding:80px 0 45px}h1{font-size:clamp(44px,8vw,78px);line-height:.95;letter-spacing:-.05em;margin:0 0 22px}p{color:#aec0b7;font-size:19px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.card{border:1px solid #35443d;border-radius:15px;padding:20px;background:#16231d}.card b{font-size:18px}.btn{display:inline-block;background:#dff06a;color:#15231d;text-decoration:none;font-weight:850;padding:12px 17px;border-radius:10px;margin:10px 8px 0 0}@media(max-width:700px){.grid{grid-template-columns:1fr}}</style></head><body><main class="w"><section class="hero"><h1>Small utilities. Stable outputs.</h1><p>Pay-per-call hashing, Base64, JWT inspection and canonical JSON for autonomous agents. Deterministic JSON responses with no account or subscription.</p><a class="btn" href="/v1/catalog">Browse tools and prices</a><a class="btn" href="/docs">Open API docs</a></section><section class="grid"><article class="card"><b>Integrity</b><p>SHA-256 and SHA-512 digests for checksums, cache keys and evidence fingerprints.</p></article><article class="card"><b>Interoperability</b><p>Encode and decode Base64 payloads or inspect JWT claims.</p></article><article class="card"><b>Stable signing input</b><p>Canonicalize JSON before hashing, comparison or signatures.</p></article></section></main></body></html>"""


@app.get("/.well-known/x402")
def x402_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Demand Microtools",
        "description": "Low-cost hashing, encoding, JWT and JSON utilities for autonomous agents.",
        "homepage": PUBLIC_ORIGIN,
        "protocol": "x402",
        "network": NETWORK,
        "asset": "USDC",
        "payTo": PAY_TO,
        "resources": tool_catalog(),
        "free_endpoints": ["/health", "/.well-known/x402", "/.well-known/agent.json", "/openapi.json", "/v1/catalog"],
    }


@app.get("/.well-known/agent.json")
def agent_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Demand Microtools",
        "protocol": "capi2.demand-tools/1.0",
        "description": "Deterministic micro-APIs priced for autonomous agent purchasing.",
        "discovery": {
            "x402": "/.well-known/x402",
            "openapi": "/openapi.json",
            "catalog": "/v1/catalog",
        },
        "payment": {"protocol": "x402", "network": NETWORK, "asset": "USDC", "price": MICRO_PRICE, "payTo": PAY_TO},
        "tools": tool_catalog(),
    }


@app.get("/v1/catalog")
def catalog() -> dict[str, Any]:
    return {"count": len(tool_catalog()), "price": MICRO_PRICE, "tools": tool_catalog()}


@app.post(
    "/v1/hash/sha256",
    tags=["hashing", "sha256", "encoding", "agent utility"],
    summary="SHA-256 hash text",
    description="Compute SHA-256 for UTF-8 text. Useful for hash, digest, checksum, integrity, cache-key and deduplication tasks.",
    openapi_extra={"x-price": MICRO_PRICE, "x-x402-price": MICRO_PRICE},
)
def sha256(payload: TextRequest) -> dict[str, Any]:
    raw = payload.text.encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return {
        "algorithm": "sha256",
        "hex": digest.hex(),
        "base64": base64.b64encode(digest).decode("ascii"),
        "bytes": len(raw),
    }


@app.post(
    "/v1/hash/sha512",
    tags=["hashing", "sha512", "encoding", "agent utility"],
    summary="SHA-512 hash text",
    description="Compute SHA-512 for UTF-8 text. Useful for hash, digest, checksum and integrity tasks.",
    openapi_extra={"x-price": MICRO_PRICE, "x-x402-price": MICRO_PRICE},
)
def sha512(payload: TextRequest) -> dict[str, Any]:
    raw = payload.text.encode("utf-8")
    digest = hashlib.sha512(raw).digest()
    return {
        "algorithm": "sha512",
        "hex": digest.hex(),
        "base64": base64.b64encode(digest).decode("ascii"),
        "bytes": len(raw),
    }


@app.post(
    "/v1/base64/encode",
    tags=["base64", "encode", "encoding", "agent utility"],
    summary="Base64 encode text",
    description="Encode UTF-8 text to standard or URL-safe Base64 for API payloads, data transport and agent interoperability.",
    openapi_extra={"x-price": MICRO_PRICE, "x-x402-price": MICRO_PRICE},
)
def base64_encode(payload: TextRequest, urlsafe: bool = False) -> dict[str, Any]:
    raw = payload.text.encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw) if urlsafe else base64.b64encode(raw)
    return {"encoding": "base64url" if urlsafe else "base64", "data": encoded.decode("ascii"), "input_bytes": len(raw)}


@app.post(
    "/v1/base64/decode",
    tags=["base64", "decode", "encoding", "agent utility"],
    summary="Base64 decode text",
    description="Decode standard or URL-safe Base64 into UTF-8 text.",
    openapi_extra={"x-price": MICRO_PRICE, "x-x402-price": MICRO_PRICE},
)
def base64_decode(payload: Base64Request) -> dict[str, Any]:
    data = payload.data.strip()
    pad = "=" * ((4 - len(data) % 4) % 4)
    try:
        raw = (base64.urlsafe_b64decode(data + pad) if payload.urlsafe else base64.b64decode(data + pad, validate=True))
        text = raw.decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=422, detail="invalid_base64_or_non_utf8_output") from exc
    return {"encoding": "base64url" if payload.urlsafe else "base64", "text": text, "output_bytes": len(raw)}


@app.post(
    "/v1/jwt/decode",
    tags=["jwt", "token", "decode", "encoding", "agent utility"],
    summary="Decode JWT claims",
    description="Decode JWT header and payload for token inspection. This does NOT verify the signature or trust the claims.",
    openapi_extra={"x-price": MICRO_PRICE, "x-x402-price": MICRO_PRICE},
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
    tags=["json", "canonicalize", "hashing", "signing", "agent utility"],
    summary="Canonicalize JSON",
    description="Serialize JSON with sorted keys and compact separators for stable hashing, comparison and signing inputs.",
    openapi_extra={"x-price": MICRO_PRICE, "x-x402-price": MICRO_PRICE},
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
            headers={"user-agent": "capi2-demand-tools/1.0"},
        )
        body = response.json() if "application/json" in response.headers.get("content-type", "") else {"text": response.text[:500]}
        print(f"agent402 registration: status={response.status_code} listed={body.get('listed')} seller={body.get('seller')}")
    except Exception as exc:
        print(f"agent402 registration deferred: {exc.__class__.__name__}: {exc}")


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=register_agent402_later, daemon=True).start()
