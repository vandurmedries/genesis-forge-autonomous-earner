from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

NAME = "CAPI2 ReceiptRail"
VERSION = "1.0.0"
PROTOCOL = "capi2.receiptrail/1.0"
ORIGIN = os.getenv("CAPI2_RECEIPTRAIL_ORIGIN", "https://capi2-receiptrail.onrender.com").rstrip("/")
PAY_TO = os.getenv("CAPI2_RECEIPTRAIL_PAY_TO", "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a")
NETWORK = os.getenv("CAPI2_RECEIPTRAIL_NETWORK", "eip155:8453")
FACILITATOR = os.getenv("CAPI2_RECEIPTRAIL_FACILITATOR", "https://facilitator.xpay.sh").rstrip("/")
PAYMENTS_OFF = os.getenv("CAPI2_RECEIPTRAIL_DISABLE_PAYMENT", "false").lower() == "true"
CACHE_TTL = int(os.getenv("CAPI2_RECEIPTRAIL_CACHE_TTL_SECONDS", "86400"))
MAX_BODY = int(os.getenv("CAPI2_RECEIPTRAIL_MAX_BODY_BYTES", "262144"))

TIERS: dict[str, dict[str, Any]] = {
    "standard": {"path": "/v1/relay/standard", "price": "$0.02", "attempts": 1, "delays": [0.0], "ack": False},
    "assured": {"path": "/v1/relay/assured", "price": "$0.10", "attempts": 4, "delays": [0.0, 0.25, 1.0, 2.0], "ack": False},
    "critical": {"path": "/v1/relay/critical", "price": "$0.50", "attempts": 5, "delays": [0.0, 0.25, 0.75, 1.5, 2.5], "ack": True},
}


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def canon(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "payload_not_canonical_json") from exc


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_key() -> Ed25519PrivateKey:
    value = os.getenv("CAPI2_RECEIPTRAIL_SIGNING_PRIVATE_KEY_B64", "").strip()
    if not value:
        raise RuntimeError("Set CAPI2_RECEIPTRAIL_SIGNING_PRIVATE_KEY_B64")
    try:
        raw = b64d(value)
        if len(raw) != 32:
            raise ValueError
        return Ed25519PrivateKey.from_private_bytes(raw)
    except Exception as exc:
        raise RuntimeError("Invalid CAPI2_RECEIPTRAIL_SIGNING_PRIVATE_KEY_B64") from exc


KEY = load_key()
PUB_RAW = KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
PUB = b64e(PUB_RAW)
KID = "ed25519:" + hashlib.sha256(PUB_RAW).hexdigest()[:24]


def sign(raw: bytes) -> str:
    return b64e(KEY.sign(raw))


def verify(raw: bytes, signature: str) -> bool:
    try:
        KEY.public_key().verify(b64d(signature), raw)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def mint(claims: dict[str, Any], kind: str) -> str:
    header = b64e(canon({"alg": "EdDSA", "kid": KID, "typ": kind}))
    payload = b64e(canon(claims))
    raw = f"{header}.{payload}".encode()
    return f"{header}.{payload}.{sign(raw)}"


def read_token(token: str, kind: str) -> dict[str, Any]:
    try:
        h, p, s = token.split(".")
        header, claims = json.loads(b64d(h)), json.loads(b64d(p))
        if not verify(f"{h}.{p}".encode(), s):
            raise ValueError
    except Exception as exc:
        raise HTTPException(401, "invalid_signed_token") from exc
    if header != {"alg": "EdDSA", "kid": KID, "typ": kind} or not isinstance(claims, dict):
        raise HTTPException(401, "signed_token_header_mismatch")
    now = int(time.time())
    if claims.get("iss") != ORIGIN or not isinstance(claims.get("exp"), int) or claims["exp"] < now:
        raise HTTPException(401, "signed_token_expired_or_wrong_issuer")
    return claims


def normalize_url(value: str) -> tuple[str, str]:
    try:
        p = urlsplit(value.strip())
    except Exception as exc:
        raise HTTPException(422, "invalid_callback_url") from exc
    if p.scheme.lower() != "https" or not p.hostname:
        raise HTTPException(422, "callback_must_be_public_https")
    if p.username or p.password or p.query or p.fragment or p.port not in (None, 443):
        raise HTTPException(422, "callback_url_contains_forbidden_parts")
    host = p.hostname.encode("idna").decode().lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".home", ".lan", ".onion")):
        raise HTTPException(422, "non_public_callback_hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise HTTPException(422, "ip_literal_callbacks_not_allowed")
    return urlunsplit(("https", host, p.path or "/", "", "")), host


async def validate_url(value: str) -> tuple[str, str]:
    url, host = normalize_url(value)

    def resolve() -> list[str]:
        return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})

    try:
        addresses = await asyncio.wait_for(asyncio.to_thread(resolve), 4.0)
    except (OSError, asyncio.TimeoutError) as exc:
        raise HTTPException(422, "callback_dns_resolution_failed") from exc
    if not addresses:
        raise HTTPException(422, "callback_dns_resolution_empty")
    for raw in addresses:
        try:
            if not ipaddress.ip_address(raw).is_global:
                raise HTTPException(422, "callback_dns_resolves_non_public_ip")
        except ValueError as exc:
            raise HTTPException(422, "callback_dns_returned_invalid_ip") from exc
    return url, host


class ChallengeIn(BaseModel):
    callback_url: str = Field(min_length=12, max_length=2048)
    service_name: str = Field(min_length=3, max_length=100)
    integration_ttl_days: int = Field(default=365, ge=1, le=365)


class VerifyIn(BaseModel):
    challenge_token: str = Field(min_length=40, max_length=8192)


class RelayIn(BaseModel):
    integration_token: str = Field(min_length=40, max_length=8192)
    event_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
    event_type: str = Field(min_length=1, max_length=200)
    source: str = Field(default="urn:capi2:external", min_length=1, max_length=300)
    payload: Any
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


class StatusIn(BaseModel):
    integration_token: str = Field(min_length=40, max_length=8192)
    event_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str | None = None


class ReceiptIn(BaseModel):
    receipt: dict[str, Any]


cache: dict[str, tuple[float, dict[str, Any]]] = {}
locks: dict[str, asyncio.Lock] = {}
state_lock = asyncio.Lock()


async def cache_get(key: str) -> dict[str, Any] | None:
    async with state_lock:
        row = cache.get(key)
        if row and row[0] > time.time():
            return row[1]
        cache.pop(key, None)
        locks.pop(key, None)
        return None


async def lock_for(key: str) -> asyncio.Lock:
    async with state_lock:
        return locks.setdefault(key, asyncio.Lock())


def integration(token: str) -> dict[str, Any]:
    claims = read_token(token, "CAPI2-INTEGRATION")
    if claims.get("use") != "integration" or not isinstance(claims.get("callback_url"), str):
        raise HTTPException(401, "invalid_integration_token")
    return claims


def signed_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    return {"payload": payload, "attestation": {"algorithm": "Ed25519", "key_id": KID, "public_key_b64": PUB, "signature_b64": sign(canon(payload)), "canonicalization": "sorted_compact_json_v1"}}


def receipt_valid(receipt: dict[str, Any]) -> bool:
    payload, att = receipt.get("payload"), receipt.get("attestation")
    return bool(isinstance(payload, dict) and isinstance(att, dict) and att.get("algorithm") == "Ed25519" and att.get("key_id") == KID and att.get("public_key_b64") == PUB and isinstance(att.get("signature_b64"), str) and verify(canon(payload), att["signature_b64"]))


async def proof(host: str) -> dict[str, Any]:
    url = f"https://{host}/.well-known/capi2-receiptrail.json"
    await validate_url(url)
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
            response = await client.get(url, headers={"user-agent": f"capi2-receiptrail/{VERSION}"})
    except httpx.HTTPError as exc:
        raise HTTPException(422, "proof_file_unreachable") from exc
    if response.status_code != 200 or len(response.content) > 16384:
        raise HTTPException(422, f"invalid_proof_file_status_{response.status_code}")
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(422, "proof_file_not_json") from exc
    if not isinstance(result, dict):
        raise HTTPException(422, "proof_file_must_be_object")
    return result


async def deliver(tier_name: str, callback_url: str, event_id: str, idem: str, body: bytes) -> tuple[int, int, str]:
    tier = TIERS[tier_name]
    digest = hashlib.sha256(body).hexdigest()
    headers = {"content-type": "application/cloudevents+json", "idempotency-key": idem, "x-capi2-event-id": event_id, "x-capi2-body-sha256": digest, "x-capi2-signature": sign(body), "x-capi2-signing-key-id": KID, "x-capi2-signing-algorithm": "Ed25519"}
    attempts: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=12, follow_redirects=False, trust_env=False) as client:
        for index in range(tier["attempts"]):
            if tier["delays"][index]:
                await asyncio.sleep(tier["delays"][index])
            url, _ = await validate_url(callback_url)
            try:
                response = await client.post(url, content=body, headers=headers)
                response_body = response.content[:65536]
                accepted = 200 <= response.status_code < 300
                if accepted and tier["ack"]:
                    try:
                        data = response.json()
                    except ValueError:
                        data = None
                    accepted = response.headers.get("x-capi2-ack") == event_id or (isinstance(data, dict) and data.get("accepted") is True and data.get("event_id") == event_id)
                attempts.append({"attempt": index + 1, "status": response.status_code, "accepted": accepted})
                if accepted:
                    return response.status_code, index + 1, hashlib.sha256(response_body).hexdigest()
            except httpx.HTTPError as exc:
                attempts.append({"attempt": index + 1, "error": exc.__class__.__name__, "accepted": False})
    raise HTTPException(502, {"code": "callback_delivery_failed", "fee_settlement": "cancelled", "attempts": attempts})


app = FastAPI(title=NAME, version=VERSION, description="Authorized webhook reliability rail with success-only x402 fees.")

if not PAYMENTS_OFF:
    from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
    from x402.http.middleware.fastapi import PaymentMiddlewareASGI
    from x402.http.types import RouteConfig
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.server import x402ResourceServer

    facilitator_client = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR))
    payment_server = x402ResourceServer(facilitator_client)
    payment_server.register(NETWORK, ExactEvmServerScheme())
    routes = {f"POST {tier['path']}": RouteConfig(accepts=[PaymentOption(scheme="exact", pay_to=PAY_TO, price=tier["price"], network=NETWORK)], resource=f"{ORIGIN}{tier['path']}", mime_type="application/json", description=f"{NAME} {name}: fee settles only after callback success.", service_name=f"{NAME} {name.title()}", tags=["webhook", "idempotency", "retries", "receipts", "x402"]) for name, tier in TIERS.items()}
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=payment_server)


@app.get("/")
async def root() -> dict[str, Any]:
    return {"name": NAME, "protocol": PROTOCOL, "model": "authorized_success_only_delivery_fee", "pricing": f"{ORIGIN}/v1/pricing", "flow": ["prove_callback_domain", "receive_signed_integration_token", "call_paid_relay", "deliver_signed_event", "settle_fee_after_success", "return_signed_receipt"]}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "capi2-receiptrail", "version": VERSION, "origin": ORIGIN, "payment_enforced": not PAYMENTS_OFF, "network": NETWORK, "asset": "USDC", "pay_to": PAY_TO, "key_id": KID, "cache": "volatile_in_memory"}


@app.get("/v1/pricing")
async def pricing() -> dict[str, Any]:
    return {"protocol": PROTOCOL, "rule": "x402 fee settles only after callback delivery succeeds", "network": NETWORK, "asset": "USDC", "pay_to": PAY_TO, "tiers": TIERS}


@app.get("/v1/public-key")
async def public_key() -> dict[str, Any]:
    return {"algorithm": "Ed25519", "key_id": KID, "public_key_b64": PUB}


@app.get("/.well-known/agent.json")
async def agent_manifest() -> dict[str, Any]:
    return {"name": NAME, "protocol": PROTOCOL, "description": "Opt-in reliability layer for webhooks and agent callbacks.", "safety": {"domain_proof_required": True, "private_targets_blocked": True, "redirects_blocked": True, "unauthorized_access": False}, "payment": {"protocol": "x402", "network": NETWORK, "asset": "USDC", "payTo": PAY_TO}, "endpoints": {"challenge": {"method": "POST", "path": "/v1/integrations/challenge", "paid": False}, "verify": {"method": "POST", "path": "/v1/integrations/verify", "paid": False}, **{name: {"method": "POST", "path": tier["path"], "paid": True, "price": tier["price"]} for name, tier in TIERS.items()}}}


@app.get("/.well-known/x402")
async def x402_manifest() -> dict[str, Any]:
    return {"name": NAME, "protocol": "x402", "network": NETWORK, "asset": "USDC", "payTo": PAY_TO, "resources": [{"method": "POST", "resource": f"{ORIGIN}{tier['path']}", "price": tier["price"], "success_only": True} for tier in TIERS.values()]}


@app.post("/v1/integrations/challenge")
async def challenge(request: ChallengeIn) -> dict[str, Any]:
    callback_url, host = await validate_url(request.callback_url)
    now = int(time.time())
    nonce = b64e(secrets.token_bytes(24))
    claims = {"iss": ORIGIN, "use": "challenge", "iat": now, "exp": now + 1800, "callback_url": callback_url, "host": host, "service_name": request.service_name, "ttl_days": request.integration_ttl_days, "nonce": nonce}
    token = mint(claims, "CAPI2-CHALLENGE")
    return {"status": "proof_required", "challenge_token": token, "proof_url": f"https://{host}/.well-known/capi2-receiptrail.json", "publish_exact_json": {"issuer": ORIGIN, "challenge": nonce, "callback_url": callback_url}}


@app.post("/v1/integrations/verify")
async def verify_integration(request: VerifyIn) -> dict[str, Any]:
    challenge = read_token(request.challenge_token, "CAPI2-CHALLENGE")
    if challenge.get("use") != "challenge":
        raise HTTPException(401, "not_a_challenge")
    callback_url, host = await validate_url(str(challenge["callback_url"]))
    expected = {"issuer": ORIGIN, "challenge": challenge["nonce"], "callback_url": callback_url}
    found = await proof(host)
    if any(found.get(k) != v for k, v in expected.items()):
        raise HTTPException(422, "proof_file_contents_mismatch")
    now = int(time.time())
    integration_id = "int_" + hashlib.sha256(f"{host}|{callback_url}|{challenge['service_name']}".encode()).hexdigest()[:24]
    claims = {"iss": ORIGIN, "use": "integration", "iat": now, "exp": now + int(challenge["ttl_days"]) * 86400, "integration_id": integration_id, "service_name": challenge["service_name"], "host": host, "callback_url": callback_url, "tiers": list(TIERS)}
    return {"status": "verified", "integration_id": integration_id, "callback_url": callback_url, "integration_token": mint(claims, "CAPI2-INTEGRATION"), "public_key_url": f"{ORIGIN}/v1/public-key"}


@app.post("/v1/receipts/verify")
async def verify_receipt(request: ReceiptIn) -> dict[str, Any]:
    return {"protocol": PROTOCOL, "valid": receipt_valid(request.receipt), "key_id": KID}


@app.post("/v1/relay/status")
async def status(request: StatusIn) -> dict[str, Any]:
    item = integration(request.integration_token)
    key = f"{item['integration_id']}:{request.idempotency_key or request.event_id}"
    receipt = await cache_get(key)
    if receipt is None:
        raise HTTPException(404, "receipt_not_in_live_cache")
    return {"status": "delivered", "receipt": receipt, "cache_ttl_seconds": CACHE_TTL}


async def relay(tier_name: str, request: RelayIn) -> dict[str, Any]:
    item = integration(request.integration_token)
    if tier_name not in item["tiers"]:
        raise HTTPException(403, "tier_not_allowed")
    callback_url, host = await validate_url(item["callback_url"])
    if host != item["host"]:
        raise HTTPException(401, "integration_host_mismatch")
    idem = request.idempotency_key or request.event_id
    key = f"{item['integration_id']}:{idem}"
    async with await lock_for(key):
        if await cache_get(key):
            raise HTTPException(409, {"code": "already_delivered", "fee_settlement": "cancelled_for_duplicate"})
        event = {"specversion": "1.0", "id": request.event_id, "source": request.source, "type": request.event_type, "time": now_iso(), "datacontenttype": "application/json", "data": request.payload, "capi2": {"protocol": PROTOCOL, "integration_id": item["integration_id"], "tier": tier_name}}
        body = canon(event)
        if len(body) > MAX_BODY:
            raise HTTPException(413, "event_payload_too_large")
        status_code, attempts, response_hash = await deliver(tier_name, callback_url, request.event_id, idem, body)
        payload = {"protocol": PROTOCOL, "receipt_id": "rcpt_" + secrets.token_hex(16), "status": "delivered", "integration_id": item["integration_id"], "event_id": request.event_id, "idempotency_key": idem, "event_type": request.event_type, "body_sha256": hashlib.sha256(body).hexdigest(), "callback_host": host, "callback_status_code": status_code, "callback_response_sha256": response_hash, "attempts": attempts, "delivered_at": now_iso(), "fee": {"display": TIERS[tier_name]["price"], "protocol": "x402", "asset": "USDC", "network": NETWORK, "settlement": "after_successful_handler"}}
        receipt = signed_receipt(payload)
        async with state_lock:
            cache[key] = (time.time() + CACHE_TTL, receipt)
        return {"protocol": PROTOCOL, "status": "delivered", "tier": tier_name, "receipt": receipt, "payment_receipt": "read Payment-Response response header"}


@app.post("/v1/relay/standard")
async def standard(request: RelayIn) -> dict[str, Any]:
    return await relay("standard", request)


@app.post("/v1/relay/assured")
async def assured(request: RelayIn) -> dict[str, Any]:
    return await relay("assured", request)


@app.post("/v1/relay/critical")
async def critical(request: RelayIn) -> dict[str, Any]:
    return await relay("critical", request)
