"""Minimal FastAPI receiver for CAPI2 AckMint callbacks.

Set ACKMINT_PUBLIC_KEY_B64 to the key published by the AckMint origin. The proof
file content is supplied at onboarding time and should be served exactly as
returned by the challenge response.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="AckMint receiver example")


def b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def public_key() -> Ed25519PublicKey:
    value = os.getenv("ACKMINT_PUBLIC_KEY_B64", "").strip()
    if not value:
        raise RuntimeError("ACKMINT_PUBLIC_KEY_B64 is required")
    return Ed25519PublicKey.from_public_bytes(b64d(value))


@app.get("/.well-known/ackmint.json")
async def ackmint_proof() -> JSONResponse:
    value = os.getenv("ACKMINT_PROOF_JSON", "").strip()
    if not value:
        raise HTTPException(503, "ACKMINT_PROOF_JSON is not configured")
    try:
        body = json.loads(value)
    except ValueError as exc:
        raise HTTPException(503, "ACKMINT_PROOF_JSON is invalid") from exc
    return JSONResponse(body)


@app.post("/webhooks/ackmint")
async def receive(
    request: Request,
    x_ackmint_signature: str = Header(alias="X-AckMint-Signature"),
    x_ackmint_body_sha256: str = Header(alias="X-AckMint-Body-SHA256"),
    x_ackmint_event_id: str = Header(alias="X-AckMint-Event-Id"),
) -> JSONResponse:
    raw = await request.body()
    if hashlib.sha256(raw).hexdigest() != x_ackmint_body_sha256:
        raise HTTPException(400, "body digest mismatch")
    try:
        public_key().verify(b64d(x_ackmint_signature), raw)
    except (InvalidSignature, ValueError) as exc:
        raise HTTPException(401, "invalid AckMint signature") from exc

    event = json.loads(raw)
    # Process the event idempotently before acknowledging it.
    return JSONResponse(
        {
            "accepted": True,
            "event_id": x_ackmint_event_id,
            "type": event.get("type"),
        },
        headers={"X-AckMint-Ack": x_ackmint_event_id},
    )
