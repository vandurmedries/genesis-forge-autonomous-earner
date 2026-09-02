"""Portable, deterministic commerce receipts for autonomous purchases.

The receipt binds request and delivery payloads to SHA-256 digests while keeping
payment settlement and delivery verification as distinct evidence classes.
Ed25519 signing is optional and enabled only when a persistent private seed is
provided through ``CAPI2_RECEIPT_ED25519_SEED``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


PROTOCOL = "capi2.commerce_receipt/1.0"


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _private_key() -> Ed25519PrivateKey | None:
    encoded = os.getenv("CAPI2_RECEIPT_ED25519_SEED", "").strip()
    if not encoded:
        return None
    try:
        seed = _b64url_decode(encoded)
    except Exception as exc:
        raise ValueError("CAPI2_RECEIPT_ED25519_SEED must be base64url") from exc
    if len(seed) != 32:
        raise ValueError("CAPI2_RECEIPT_ED25519_SEED must decode to 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_signing_key() -> dict[str, Any]:
    key = _private_key()
    if key is None:
        return {"enabled": False, "algorithm": "Ed25519"}
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "enabled": True,
        "algorithm": "Ed25519",
        "key_id": "capi2-receipts-v1",
        "public_key": _b64url(raw),
    }


def issue_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    request = payload["request"]
    delivery = payload["delivery"]
    issued_at = payload.get("issued_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    request_sha256 = sha256_json(request)
    delivery_sha256 = sha256_json(delivery)
    identity = {
        "seller": payload["seller"],
        "request_sha256": request_sha256,
        "delivery_sha256": delivery_sha256,
        "idempotency_key": payload.get("idempotency_key"),
    }
    receipt = {
        "protocol": PROTOCOL,
        "receipt_id": "cr_" + sha256_json(identity)[:32],
        "request_id": payload["request_id"],
        "idempotency_key": payload.get("idempotency_key"),
        "buyer_agent": payload.get("buyer_agent"),
        "seller": payload["seller"],
        "authority": payload.get("authority"),
        "policy_decision": payload.get("policy_decision"),
        "price": payload["price"],
        "asset": payload["asset"],
        "network": payload["network"],
        "request_sha256": request_sha256,
        "delivery_sha256": delivery_sha256,
        "request": request,
        "delivery": delivery,
        "verification": payload.get("verification"),
        "settlement": payload.get("settlement"),
        "issued_at": issued_at,
        "evidence_classes": {
            "payment": "settlement evidence only",
            "delivery": "content hash binding only",
            "quality": "verification verdict and evidence, when supplied",
        },
        "limitations": [
            "Settlement does not prove delivery quality.",
            "A content hash proves payload integrity, not truth or fitness for purpose.",
        ],
    }
    key = _private_key()
    if key is None:
        receipt["attestation"] = {"signed": False, "reason": "signing_key_not_configured"}
        return receipt
    signable = canonical_json(receipt)
    signature = key.sign(signable)
    receipt["attestation"] = {
        "signed": True,
        "algorithm": "Ed25519",
        "key_id": "capi2-receipts-v1",
        "public_key": public_signing_key()["public_key"],
        "signature": _b64url(signature),
    }
    return receipt


def verify_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    required = [
        "protocol", "receipt_id", "request_id", "seller", "price", "asset", "network",
        "request_sha256", "delivery_sha256", "request", "delivery", "issued_at",
    ]
    missing = [field for field in required if receipt.get(field) in (None, "", {})]
    warnings: list[str] = []
    if receipt.get("protocol") != PROTOCOL:
        warnings.append("unsupported_protocol")
    for field, payload_field in (("request_sha256", "request"), ("delivery_sha256", "delivery")):
        digest = receipt.get(field)
        if digest and not isinstance(digest, str):
            warnings.append(f"{field}_invalid")
        elif digest and digest != sha256_json(receipt.get(payload_field)):
            warnings.append(f"{field}_mismatch")
    expected_identity = {
        "seller": receipt.get("seller"),
        "request_sha256": receipt.get("request_sha256"),
        "delivery_sha256": receipt.get("delivery_sha256"),
        "idempotency_key": receipt.get("idempotency_key"),
    }
    expected_id = "cr_" + sha256_json(expected_identity)[:32]
    if receipt.get("receipt_id") and receipt["receipt_id"] != expected_id:
        warnings.append("receipt_id_mismatch")

    attestation = receipt.get("attestation") or {}
    signature_valid: bool | None = None
    if attestation.get("signed") is True:
        try:
            public_key = Ed25519PublicKey.from_public_bytes(_b64url_decode(attestation["public_key"]))
            signature = _b64url_decode(attestation["signature"])
            unsigned = dict(receipt)
            unsigned.pop("attestation", None)
            public_key.verify(signature, canonical_json(unsigned))
            signature_valid = True
        except (InvalidSignature, KeyError, TypeError, ValueError):
            signature_valid = False
            warnings.append("signature_invalid")
    elif attestation.get("signed") is False:
        warnings.append("receipt_unsigned")

    return {
        "protocol": "capi2.commerce_receipt_verify/1.0",
        "valid": not missing and not [warning for warning in warnings if warning != "receipt_unsigned"],
        "integrity_valid": not any(w.endswith("_mismatch") or w.endswith("_invalid") for w in warnings),
        "signature_valid": signature_valid,
        "missing": missing,
        "warnings": warnings,
        "receipt_id": receipt.get("receipt_id"),
        "verification_scope": "payload integrity and optional signature; settlement and delivery quality are not independently verified",
    }
