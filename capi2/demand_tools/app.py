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
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from x402.extensions.bazaar import OutputConfig, declare_discovery_extension
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
    title="capi2 Agent Utilities",
    version="1.1.0",
    description=(
        "Ultra-low-cost x402 utilities for autonomous agents: hashing, checksums, Base64, "
        "JWT inspection and deterministic JSON canonicalization."
    ),
)

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
server = x402ResourceServer(facilitator)
server.register(NETWORK, ExactEvmServerScheme())

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

BUYER_QUERIES = [
    "sha256 checksum or digest",
    "sha512 checksum or digest",
    "base64 encode or decode",
    "decode jwt claims without verification",
    "canonicalize json for hashing or signing",
]


def paid(
    path: str,
    service_name: str,
    description: str,
    tags: list[str],
    input_example: dict[str, Any],
    input_schema: dict[str, Any],
    output_example: dict[str, Any],
) -> RouteConfig:
    return RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                pay_to=PAY_TO,
                price=MICRO_PRICE,
                network=NETWORK,
            )
        ],
        resource=f"{PUBLIC_ORIGIN}{path}",
        mime_type="application/json",
        description=description,
        service_name=service_name,
        tags=tags,
        extensions=declare_discovery_extension(
            input=input_example,
            input_schema=input_schema,
            body_type="json",
            output=OutputConfig(example=output_example),
        ),
    )


routes = {
    "POST /v1/hash/sha256": paid(
        "/v1/hash/sha256",
        "capi2 SHA-256",
        "Compute a SHA-256 checksum/digest for text for integrity checks, cache keys and deduplication.",
        ["sha256", "checksum", "integrity", "cache key", "deduplication"],
        {"text": "hello agent"},
        TEXT_SCHEMA,
        {"algorithm": "sha256", "hex": "55ea...", "base64": "Veo...", "bytes": 11},
    ),
    "POST /v1/hash/sha512": paid(
        "/v1/hash/sha512",
        "capi2 SHA-512",
        "Compute a SHA-512 checksum/digest for text for integrity and deterministic agent workflows.",
        ["sha512", "checksum", "integrity", "digest", "developer tools"],
        {"text": "hello agent"},
        TEXT_SCHEMA,
        {"algorithm": "sha512", "hex": "db39...", "base64": "2zk...", "bytes": 11},
    ),
    "POST /v1/base64/encode": paid(
        "/v1/base64/encode",
        "capi2 Base64 Encode",
        "Encode UTF-8 text to Base64 for API payloads, transport and agent interoperability.",
        ["base64", "encode", "api payload", "data transport", "developer tools"],
        {"text": "hello agent"},
        TEXT_SCHEMA,
        {"encoding": "base64", "data": "aGVsbG8gYWdlbnQ=", "input_bytes": 11},
    ),
    "POST /v1/base64/decode": paid(
        "/v1/base64/decode",
        "capi2 Base64 Decode",
        "Decode Base64 or Base64URL data into UTF-8 text for API and agent workflows.",
        ["base64", "decode", "base64url", "api payload", "developer tools"],
        {"data": "aGVsbG8gYWdlbnQ=", "urlsafe": False},
        BASE64_DECODE_SCHEMA,
        {"encoding": "base64", "text": "hello agent", "output_bytes": 11},
    ),
    "POST /v1/jwt/decode": paid(
        "/v1/jwt/decode",
        "capi2 JWT Decode",
        "Decode JWT header and claims without signature verification for token inspection and debugging.",
        ["jwt", "token inspection", "auth debugging", "decode", "developer tools"],
        {"token": "eyJhbGciOiJub25lIn0.eyJzdWIiOiIxMjMifQ."},
        JWT_SCHEMA,
        {"header": {"alg": "none"}, "payload": {"sub": "123"}, "signature_present": False, "verified": False},
    ),
    "POST /v1/json/canonicalize": paid(
        "/v1/json/canonicalize",
        "capi2 JSON Canonical",
        "Canonicalize JSON with sorted keys and compact separators for stable hashing, signing and comparison.",
        ["json", "canonicalization", "signing", "deterministic", "hashing"],
        {"value": {"b": 2, "a": 1}},
        JSON_CANONICALIZE_SCHEMA,
        {"canonical": "{\"a\":1,\"b\":2}", "sha256": "43258cff..."},
    ),
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
            "service_name": "capi2 SHA-256",
            "endpoint": "POST /v1/hash/sha256",
            "resource": f"{PUBLIC_ORIGIN}/v1/hash/sha256",
            "method": "POST",
            "price_usd": p,
            "tags": ["sha256", "checksum", "integrity", "cache key", "deduplication"],
            "buyer_queries": ["sha256 checksum", "hash text", "content digest", "deduplicate content"],
            "example_request": {"text": "hello agent"},
            "summary": "SHA-256 digest for integrity checks, cache keys and deduplication.",
        },
        {
            "name": "SHA-512 hash",
            "service_name": "capi2 SHA-512",
            "endpoint": "POST /v1/hash/sha512",
            "resource": f"{PUBLIC_ORIGIN}/v1/hash/sha512",
            "method": "POST",
            "price_usd": p,
            "tags": ["sha512", "checksum", "integrity", "digest", "developer tools"],
            "buyer_queries": ["sha512 checksum", "sha512 digest", "hash text with sha512"],
            "example_request": {"text": "hello agent"},
            "summary": "SHA-512 digest for integrity and deterministic workflows.",
        },
        {
            "name": "Base64 encode",
            "service_name": "capi2 Base64 Encode",
            "endpoint": "POST /v1/base64/encode",
            "resource": f"{PUBLIC_ORIGIN}/v1/base64/encode",
            "method": "POST",
            "price_usd": p,
            "tags": ["base64", "encode", "api payload", "data transport", "developer tools"],
            "buyer_queries": ["base64 encode text", "encode api payload", "convert text to base64"],
            "example_request": {"text": "hello agent"},
            "summary": "Encode UTF-8 text to Base64.",
        },
        {
            "name": "Base64 decode",
            "service_name": "capi2 Base64 Decode",
            "endpoint": "POST /v1/base64/decode",
            "resource": f"{PUBLIC_ORIGIN}/v1/base64/decode",
            "method": "POST",
            "price_usd": p,
            "tags": ["base64", "decode", "base64url", "api payload", "developer tools"],
            "buyer_queries": ["base64 decode", "decode base64url", "convert base64 to text"],
            "example_request": {"data": "aGVsbG8gYWdlbnQ=", "urlsafe": False},
            "summary": "Decode Base64 or Base64URL into UTF-8 text.",
        },
        {
            "name": "JWT decode",
            "service_name": "capi2 JWT Decode",
            "endpoint": "POST /v1/jwt/decode",
            "resource": f"{PUBLIC_ORIGIN}/v1/jwt/decode",
            "method": "POST",
            "price_usd": p,
            "tags": ["jwt", "token inspection", "auth debugging", "decode", "developer tools"],
            "buyer_queries": ["decode jwt claims", "inspect jwt payload", "debug bearer token"],
            "example_request": {"token": "header.payload.signature"},
            "summary": "Decode JWT header and claims without verifying the signature.",
        },
        {
            "name": "JSON canonicalize",
            "service_name": "capi2 JSON Canonical",
            "endpoint": "POST /v1/json/canonicalize",
            "resource": f"{PUBLIC_ORIGIN}/v1/json/canonicalize",
            "method": "POST",
            "price_usd": p,
            "tags": ["json", "canonicalization", "signing", "deterministic", "hashing"],
            "buyer_queries": ["canonicalize json", "stable json for signing", "deterministic json hash"],
            "example_request": {"value": {"b": 2, "a": 1}},
            "summary": "Canonicalize JSON for stable hashing, signing and comparison.",
        },
    ]


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "name": "capi2 Agent Utilities",
        "paid": True,
        "price_per_tool": MICRO_PRICE,
        "asset": "USDC",
        "network": NETWORK,
        "buyer_queries": BUYER_QUERIES,
        "discover": {
            "x402": f"{PUBLIC_ORIGIN}/.well-known/x402",
            "agent": f"{PUBLIC_ORIGIN}/.well-known/agent.json",
            "openapi": f"{PUBLIC_ORIGIN}/openapi.json",
            "catalog": f"{PUBLIC_ORIGIN}/v1/catalog",
            "llms": f"{PUBLIC_ORIGIN}/llms.txt",
        },
        "tools": tool_catalog(),
    }


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
        "bazaar_discovery": True,
        "positioning": "low-cost x402 developer and agent utility lane",
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
    lines = [
        "# capi2 Agent Utilities",
        "",
        "Low-cost paid x402 utilities for autonomous agents and developer workflows.",
        f"Price per call: {MICRO_PRICE} USDC on {NETWORK}.",
        f"Pay to: {PAY_TO}",
        "",
        "Use when the task asks for:",
        "- SHA-256 or SHA-512 checksum/digest",
        "- Base64/Base64URL encode or decode",
        "- JWT header/claims decoding for inspection",
        "- deterministic JSON canonicalization for hashing/signing",
        "",
        f"x402 discovery: {PUBLIC_ORIGIN}/.well-known/x402",
        f"agent manifest: {PUBLIC_ORIGIN}/.well-known/agent.json",
        f"catalog: {PUBLIC_ORIGIN}/v1/catalog",
        f"OpenAPI: {PUBLIC_ORIGIN}/openapi.json",
        "",
        "Each unpaid POST returns HTTP 402; pay and retry with x402 proof to receive the JSON result.",
    ]
    return "\n".join(lines) + "\n"


@app.get("/.well-known/x402")
def x402_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Agent Utilities",
        "description": "Low-cost hashing, checksum, encoding, JWT and JSON utilities for autonomous agents.",
        "homepage": PUBLIC_ORIGIN,
        "protocol": "x402",
        "network": NETWORK,
        "asset": "USDC",
        "payTo": PAY_TO,
        "buyer_queries": BUYER_QUERIES,
        "resources": tool_catalog(),
        "free_endpoints": [
            "/",
            "/health",
            "/robots.txt",
            "/llms.txt",
            "/.well-known/x402",
            "/.well-known/agent.json",
            "/openapi.json",
            "/v1/catalog",
        ],
    }


@app.get("/.well-known/agent.json")
def agent_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Agent Utilities",
        "protocol": "capi2.demand-tools/1.1",
        "description": "Deterministic micro-APIs priced for autonomous agent purchasing.",
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
            "price": MICRO_PRICE,
            "payTo": PAY_TO,
        },
        "tools": tool_catalog(),
    }


@app.get("/v1/catalog")
def catalog() -> dict[str, Any]:
    return {
        "count": len(tool_catalog()),
        "price": MICRO_PRICE,
        "asset": "USDC",
        "network": NETWORK,
        "buyer_queries": BUYER_QUERIES,
        "tools": tool_catalog(),
    }


@app.post(
    "/v1/hash/sha256",
    tags=["hashing", "sha256", "checksum", "integrity", "agent utility"],
    summary="SHA-256 hash text",
    description="Compute SHA-256 for UTF-8 text. Useful for checksums, integrity, cache keys and deduplication.",
    openapi_extra={"x-price": MICRO_PRICE, "x-x402-price": MICRO_PRICE, "x-bazaar-discoverable": True},
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
    tags=["hashing", "sha512", "checksum", "integrity", "agent utility"],
    summary="SHA-512 hash text",
    description="Compute SHA-512 for UTF-8 text. Useful for checksums, integrity and deterministic workflows.",
    openapi_extra={"x-price": MICRO_PRICE, "x-x402-price": MICRO_PRICE, "x-bazaar-discoverable": True},
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
    tags=["base64", "encode", "encoding", "api payload", "agent utility"],
    summary="Base64 encode text",
    description="Encode UTF-8 text to Base64 for API payloads, data transport and agent interoperability.",
    openapi_extra={"x-price": MICRO_PRICE, "x-x402-price": MICRO_PRICE, "x-bazaar-discoverable": True},
)
def base64_encode(payload: TextRequest, urlsafe: bool = False) -> dict[str, Any]:
    raw = payload.text.encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw) if urlsafe else base64.b64encode(raw)
    return {"encoding": "base64url" if urlsafe else "base64", "data": encoded.decode("ascii"), "input_bytes": len(raw)}


@app.post(
    "/v1/base64/decode",
    tags=["base64", "decode", "base64url", "api payload", "agent utility"],
    summary="Base64 decode text",
    description="Decode standard or URL-safe Base64 into UTF-8 text.",
    openapi_extra={"x-price": MICRO_PRICE, "x-x402-price": MICRO_PRICE, "x-bazaar-discoverable": True},
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
    tags=["jwt", "token", "decode", "auth debugging", "agent utility"],
    summary="Decode JWT claims",
    description="Decode JWT header and payload for token inspection. This does NOT verify the signature or trust the claims.",
    openapi_extra={"x-price": MICRO_PRICE, "x-x402-price": MICRO_PRICE, "x-bazaar-discoverable": True},
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
    openapi_extra={"x-price": MICRO_PRICE, "x-x402-price": MICRO_PRICE, "x-bazaar-discoverable": True},
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
            headers={"user-agent": "capi2-demand-tools/1.1"},
        )
        body = response.json() if "application/json" in response.headers.get("content-type", "") else {"text": response.text[:500]}
        print(f"agent402 registration: status={response.status_code} listed={body.get('listed')} seller={body.get('seller')}")
    except Exception as exc:
        print(f"agent402 registration deferred: {exc.__class__.__name__}: {exc}")


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=register_agent402_later, daemon=True).start()
