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
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import psycopg
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from pydantic import BaseModel, Field

NAME = "CAPI2 AckMint"
VERSION = "1.0.0"
PROTOCOL = "capi2.ackmint/1.0"
ORIGIN = os.getenv(
    "ACKMINT_ORIGIN",
    "https://capi2-agent-marketplace-router.onrender.com",
).rstrip("/")
PAY_TO = os.getenv(
    "ACKMINT_PAY_TO",
    "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a",
)
NETWORK = os.getenv("ACKMINT_NETWORK", "eip155:8453")
FACILITATOR = os.getenv(
    "ACKMINT_FACILITATOR",
    "https://facilitator.xpay.sh",
).rstrip("/")
PAYMENTS_OFF = os.getenv("ACKMINT_DISABLE_PAYMENT", "false").lower() == "true"
RETENTION_DAYS = int(os.getenv("ACKMINT_RETENTION_DAYS", "90"))
MAX_BODY = int(os.getenv("ACKMINT_MAX_BODY_BYTES", "262144"))
LEASE_SECONDS = int(os.getenv("ACKMINT_LEASE_SECONDS", "120"))
SETUP_URL = os.getenv("ACKMINT_SETUP_URL", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

TIERS: dict[str, dict[str, Any]] = {
    "standard": {
        "path": "/v1/ackmint/relay/standard",
        "price": "$0.02",
        "attempts": 1,
        "delays": [0.0],
        "ack": False,
    },
    "assured": {
        "path": "/v1/ackmint/relay/assured",
        "price": "$0.08",
        "attempts": 4,
        "delays": [0.0, 0.25, 1.0, 2.0],
        "ack": False,
    },
    "critical": {
        "path": "/v1/ackmint/relay/critical",
        "price": "$0.25",
        "attempts": 5,
        "delays": [0.0, 0.25, 0.75, 1.5, 2.5],
        "ack": True,
    },
}


class ChallengeIn(BaseModel):
    callback_url: str = Field(min_length=12, max_length=2048)
    service_name: str = Field(min_length=3, max_length=100)
    integration_ttl_days: int = Field(default=365, ge=1, le=365)


class VerifyIn(BaseModel):
    challenge_token: str = Field(min_length=40, max_length=8192)


class RelayIn(BaseModel):
    integration_token: str = Field(min_length=40, max_length=8192)
    event_id: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$",
    )
    event_type: str = Field(min_length=1, max_length=200)
    source: str = Field(
        default="urn:capi2:external",
        min_length=1,
        max_length=300,
    )
    payload: Any
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$",
    )


class StatusIn(BaseModel):
    integration_token: str = Field(min_length=40, max_length=8192)
    event_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=200)


class ReceiptIn(BaseModel):
    receipt: dict[str, Any]


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def canon(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "payload_not_canonical_json") from exc


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_key() -> Ed25519PrivateKey:
    value = os.getenv("ACKMINT_SIGNING_PRIVATE_KEY_B64", "").strip()
    if not value:
        raise RuntimeError("Set ACKMINT_SIGNING_PRIVATE_KEY_B64")
    try:
        raw = b64d(value)
        if len(raw) != 32:
            raise ValueError
        return Ed25519PrivateKey.from_private_bytes(raw)
    except Exception as exc:
        raise RuntimeError("Invalid ACKMINT_SIGNING_PRIVATE_KEY_B64") from exc


KEY = load_key()
PUB_RAW = KEY.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
)
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
        header_b64, payload_b64, signature = token.split(".")
        header = json.loads(b64d(header_b64))
        claims = json.loads(b64d(payload_b64))
        if not verify(f"{header_b64}.{payload_b64}".encode(), signature):
            raise ValueError
    except Exception as exc:
        raise HTTPException(401, "invalid_signed_token") from exc
    expected = {"alg": "EdDSA", "kid": KID, "typ": kind}
    if header != expected or not isinstance(claims, dict):
        raise HTTPException(401, "signed_token_header_mismatch")
    now = int(time.time())
    if (
        claims.get("iss") != ORIGIN
        or not isinstance(claims.get("exp"), int)
        or claims["exp"] < now
    ):
        raise HTTPException(401, "signed_token_expired_or_wrong_issuer")
    return claims


def normalize_url(value: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(value.strip())
    except Exception as exc:
        raise HTTPException(422, "invalid_callback_url") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise HTTPException(422, "callback_must_be_public_https")
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise HTTPException(422, "callback_url_contains_forbidden_parts")
    host = parsed.hostname.encode("idna").decode().lower().rstrip(".")
    if host == "localhost" or host.endswith(
        (".localhost", ".local", ".internal", ".home", ".lan", ".onion")
    ):
        raise HTTPException(422, "non_public_callback_hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise HTTPException(422, "ip_literal_callbacks_not_allowed")
    return urlunsplit(("https", host, parsed.path or "/", "", "")), host


async def validate_url(value: str) -> tuple[str, str]:
    url, host = normalize_url(value)

    def resolve() -> list[str]:
        return sorted(
            {
                str(info[4][0])
                for info in socket.getaddrinfo(
                    host,
                    443,
                    type=socket.SOCK_STREAM,
                )
            }
        )

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


def integration(token: str) -> dict[str, Any]:
    claims = read_token(token, "ACKMINT-INTEGRATION")
    if (
        claims.get("use") != "integration"
        or not isinstance(claims.get("callback_url"), str)
    ):
        raise HTTPException(401, "invalid_integration_token")
    return claims


def signed_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "payload": payload,
        "attestation": {
            "algorithm": "Ed25519",
            "key_id": KID,
            "public_key_b64": PUB,
            "signature_b64": sign(canon(payload)),
            "canonicalization": "sorted_compact_json_v1",
        },
    }


def receipt_valid(receipt: dict[str, Any]) -> bool:
    payload = receipt.get("payload")
    attestation = receipt.get("attestation")
    return bool(
        isinstance(payload, dict)
        and isinstance(attestation, dict)
        and attestation.get("algorithm") == "Ed25519"
        and attestation.get("key_id") == KID
        and attestation.get("public_key_b64") == PUB
        and isinstance(attestation.get("signature_b64"), str)
        and verify(canon(payload), attestation["signature_b64"])
    )


async def domain_proof(host: str) -> dict[str, Any]:
    url = f"https://{host}/.well-known/ackmint.json"
    await validate_url(url)
    try:
        async with httpx.AsyncClient(
            timeout=5,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get(
                url,
                headers={"user-agent": f"ackmint/{VERSION}"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(422, "proof_file_unreachable") from exc
    if response.status_code != 200 or len(response.content) > 16384:
        raise HTTPException(
            422,
            f"invalid_proof_file_status_{response.status_code}",
        )
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(422, "proof_file_not_json") from exc
    if not isinstance(result, dict):
        raise HTTPException(422, "proof_file_must_be_object")
    return result


def connect():
    if not DATABASE_URL:
        raise HTTPException(503, "persistent_database_not_configured")
    return psycopg.connect(DATABASE_URL, connect_timeout=5)


def init_db() -> None:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required for AckMint")
    with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ackmint_deliveries (
                    storage_key TEXT PRIMARY KEY,
                    lease_token TEXT NOT NULL,
                    status TEXT NOT NULL,
                    integration_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL,
                    callback_host TEXT NOT NULL,
                    receipt JSONB,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    lease_until TIMESTAMPTZ,
                    expires_at TIMESTAMPTZ NOT NULL,
                    CHECK (status IN ('processing', 'delivered'))
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS ackmint_deliveries_expires_idx
                ON ackmint_deliveries (expires_at)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS ackmint_deliveries_status_idx
                ON ackmint_deliveries (status, updated_at)
                """
            )
        conn.commit()


def storage_key(integration_id: str, idem: str) -> str:
    return hashlib.sha256(f"{integration_id}\0{idem}".encode()).hexdigest()


def reserve_sync(
    *,
    key: str,
    integration_id: str,
    event_id: str,
    idempotency_key: str,
    event_type: str,
    tier: str,
    body_sha256: str,
    callback_host: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    lease_until = now + timedelta(seconds=LEASE_SECONDS)
    expires_at = now + timedelta(days=RETENTION_DAYS)
    lease_token = secrets.token_urlsafe(24)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ackmint_deliveries WHERE expires_at < NOW()")
            cur.execute(
                """
                INSERT INTO ackmint_deliveries (
                    storage_key, lease_token, status, integration_id,
                    event_id, idempotency_key, event_type, tier,
                    body_sha256, callback_host, receipt, created_at,
                    updated_at, lease_until, expires_at
                ) VALUES (
                    %s, %s, 'processing', %s, %s, %s, %s, %s,
                    %s, %s, NULL, %s, %s, %s, %s
                ) ON CONFLICT (storage_key) DO NOTHING
                RETURNING storage_key
                """,
                (
                    key,
                    lease_token,
                    integration_id,
                    event_id,
                    idempotency_key,
                    event_type,
                    tier,
                    body_sha256,
                    callback_host,
                    now,
                    now,
                    lease_until,
                    expires_at,
                ),
            )
            if cur.fetchone():
                conn.commit()
                return {"state": "reserved", "lease_token": lease_token}
            cur.execute(
                """
                SELECT status, lease_until, receipt
                FROM ackmint_deliveries
                WHERE storage_key = %s FOR UPDATE
                """,
                (key,),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                raise RuntimeError("reservation_conflict_without_row")
            status, current_lease_until, receipt = row
            if status == "delivered":
                conn.commit()
                return {"state": "delivered", "receipt": receipt}
            if current_lease_until is not None and current_lease_until <= now:
                cur.execute(
                    """
                    UPDATE ackmint_deliveries
                    SET lease_token=%s, updated_at=%s, lease_until=%s,
                        expires_at=%s
                    WHERE storage_key=%s
                    """,
                    (lease_token, now, lease_until, expires_at, key),
                )
                conn.commit()
                return {
                    "state": "reserved",
                    "lease_token": lease_token,
                    "reclaimed": True,
                }
            conn.commit()
            return {"state": "processing"}


async def reserve(**kwargs: Any) -> dict[str, Any]:
    return await asyncio.to_thread(reserve_sync, **kwargs)


def complete_sync(key: str, lease_token: str, receipt: dict[str, Any]) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ackmint_deliveries
                SET status='delivered', receipt=%s::jsonb,
                    updated_at=NOW(), lease_until=NULL
                WHERE storage_key=%s AND lease_token=%s
                  AND status='processing'
                """,
                (json.dumps(receipt), key, lease_token),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise RuntimeError("ackmint_completion_lease_lost")
        conn.commit()


async def complete(key: str, lease_token: str, receipt: dict[str, Any]) -> None:
    last_error: Exception | None = None
    for delay in (0.0, 0.2, 0.8):
        if delay:
            await asyncio.sleep(delay)
        try:
            await asyncio.to_thread(complete_sync, key, lease_token, receipt)
            return
        except Exception as exc:
            last_error = exc
    raise HTTPException(
        503,
        {
            "code": "delivery_succeeded_but_receipt_persistence_failed",
            "fee_settlement": "cancelled",
            "error": last_error.__class__.__name__ if last_error else "unknown",
        },
    )


def release_sync(key: str, lease_token: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM ackmint_deliveries
                WHERE storage_key=%s AND lease_token=%s
                  AND status='processing'
                """,
                (key, lease_token),
            )
        conn.commit()


async def release(key: str, lease_token: str) -> None:
    try:
        await asyncio.to_thread(release_sync, key, lease_token)
    except Exception:
        pass


def get_sync(key: str) -> dict[str, Any] | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, receipt, updated_at, expires_at
                FROM ackmint_deliveries
                WHERE storage_key=%s AND expires_at >= NOW()
                """,
                (key,),
            )
            row = cur.fetchone()
    if not row:
        return None
    status, receipt, updated_at, expires_at = row
    return {
        "status": status,
        "receipt": receipt,
        "updated_at": updated_at,
        "expires_at": expires_at,
    }


async def get(key: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(get_sync, key)


def stats_sync() -> dict[str, int]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status='delivered'),
                    COUNT(*) FILTER (
                        WHERE status='delivered'
                          AND updated_at >= NOW() - INTERVAL '24 hours'
                    ),
                    COUNT(DISTINCT integration_id) FILTER (
                        WHERE status='delivered'
                    )
                FROM ackmint_deliveries
                WHERE expires_at >= NOW()
                """
            )
            delivered, last_24h, integrations = cur.fetchone()
    return {
        "retained_successful_deliveries": int(delivered or 0),
        "successful_deliveries_last_24h": int(last_24h or 0),
        "integrations_with_successful_delivery": int(integrations or 0),
    }


async def deliver(
    tier_name: str,
    callback_url: str,
    event_id: str,
    idem: str,
    body: bytes,
) -> tuple[int, int, str, list[dict[str, Any]]]:
    tier = TIERS[tier_name]
    digest = hashlib.sha256(body).hexdigest()
    headers = {
        "content-type": "application/cloudevents+json",
        "idempotency-key": idem,
        "x-ackmint-event-id": event_id,
        "x-ackmint-body-sha256": digest,
        "x-ackmint-signature": sign(body),
        "x-ackmint-signing-key-id": KID,
        "x-ackmint-signing-algorithm": "Ed25519",
    }
    attempts: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=12,
        follow_redirects=False,
        trust_env=False,
    ) as client:
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
                    accepted = (
                        response.headers.get("x-ackmint-ack") == event_id
                        or (
                            isinstance(data, dict)
                            and data.get("accepted") is True
                            and data.get("event_id") == event_id
                        )
                    )
                attempts.append(
                    {
                        "attempt": index + 1,
                        "status": response.status_code,
                        "accepted": accepted,
                    }
                )
                if accepted:
                    return (
                        response.status_code,
                        index + 1,
                        hashlib.sha256(response_body).hexdigest(),
                        attempts,
                    )
            except httpx.HTTPError as exc:
                attempts.append(
                    {
                        "attempt": index + 1,
                        "error": exc.__class__.__name__,
                        "accepted": False,
                    }
                )
    raise HTTPException(
        502,
        {
            "code": "callback_delivery_failed",
            "fee_settlement": "cancelled",
            "attempts": attempts,
        },
    )
