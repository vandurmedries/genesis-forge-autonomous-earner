"""Register capi2 Claim Verify with the public true402 x402 marketplace.

This is distribution-only. It does not patch FastAPI, x402 middleware, payment
verification, or settlement. Registration is delayed until the service is up and
uses true402's documented inline-manifest contract so capi2 does not need a new
public route just to be listed.
"""
from __future__ import annotations

import os
import threading
import time

import requests

ORIGIN = os.getenv(
    "CAPI2_CLAIM_VERIFY_ORIGIN",
    "https://capi2-claim-verify.onrender.com",
).rstrip("/")
PAY_TO = os.getenv(
    "CAPI2_PAY_TO",
    "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a",
)
FACILITATOR = os.getenv(
    "CAPI2_X402_FACILITATOR",
    "https://facilitator.xpay.sh",
).rstrip("/")
REGISTER_URL = "https://true402.dev/api/v1/services/register"
ENABLED = os.getenv("CAPI2_TRUE402_REGISTER", "true").lower() == "true"


def _payload() -> dict:
    return {
        "url": ORIGIN,
        "manifest": {
            "x402": "1.0",
            "name": "capi2 Claim Verify",
            "description": (
                "Evidence-backed public-source claim verification for AI agents "
                "performing vendor risk, due diligence, procurement, RFP, security "
                "and commercial fact checking."
            ),
            "capabilities": [
                "claim-verification",
                "vendor-risk",
                "due-diligence",
                "procurement",
                "fact-checking",
            ],
            "pricing": {"currency": "USDC", "base": "0.01", "unit": "request"},
            "payment": {
                "address": PAY_TO,
                "chain": "base",
                "facilitator": FACILITATOR,
            },
            "endpoint": f"{ORIGIN}/v1/claim-verify",
        },
    }


def _register() -> None:
    # Let Uvicorn finish importing and bind before the external registry checks us.
    time.sleep(25)
    try:
        response = requests.post(
            REGISTER_URL,
            json=_payload(),
            timeout=20,
            headers={
                "content-type": "application/json",
                "user-agent": "capi2-claim-verify/1.5.0 (+true402-registration)",
            },
        )
        try:
            body = response.json()
        except ValueError:
            body = {"text": response.text[:1000]}
        print(
            "true402 registration: "
            f"status={response.status_code} body={body}",
            flush=True,
        )
    except Exception as exc:
        print(
            f"true402 registration deferred: {type(exc).__name__}: {exc}",
            flush=True,
        )


if ENABLED:
    threading.Thread(target=_register, daemon=True).start()
