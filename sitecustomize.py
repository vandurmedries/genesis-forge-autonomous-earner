"""One-shot capi2 x402 directory distribution hook.

Python imports sitecustomize automatically at interpreter startup. This hook is
strictly gated by CAPI2_DIRECTORY_DISTRIBUTE=true and by the Claim Verify
uvicorn target, so normal repo processes are unaffected. It performs free,
best-effort directory submissions from Render's production network and never
attempts a payment.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


def _is_claim_verify_process() -> bool:
    return any("capi2.x402_service.app:app" in str(arg) for arg in sys.argv)


def _post_json(url: str, payload: dict, label: str) -> tuple[int | None, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "capi2-directory-distributor/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
            print(f"directory-distribution {label}: HTTP {response.status} {body[:1600]}", flush=True)
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        print(f"directory-distribution {label}: HTTP {exc.code} {body[:1600]}", flush=True)
        return exc.code, body
    except Exception as exc:
        print(f"directory-distribution {label}: ERROR {type(exc).__name__}: {exc}", flush=True)
        return None, ""


def _post_form(url: str, payload: dict, label: str) -> tuple[int | None, str]:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "capi2-directory-distributor/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
            print(f"directory-distribution {label}: HTTP {response.status} {body[:1600]}", flush=True)
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        print(f"directory-distribution {label}: HTTP {exc.code} {body[:1600]}", flush=True)
        return exc.code, body
    except Exception as exc:
        print(f"directory-distribution {label}: ERROR {type(exc).__name__}: {exc}", flush=True)
        return None, ""


def _registrations() -> list[dict]:
    return [
        {
            "url": "https://capi2-claim-verify.onrender.com/v1/claim-verify",
            "name": "capi2 Claim Verify",
            "probe": {"vendor_url": "https://example.com/security", "claim": "Vendor states that customer data is encrypted at rest."},
            "description": "Evidence-backed vendor claim verification for AI agents, procurement, due diligence, RFP and security workflows.",
            "price": 0.01,
            "category": "ai/vendor-risk",
        },
        {
            "url": "https://capi2-demand-tools.onrender.com/v1/hash/sha256",
            "name": "capi2 SHA-256",
            "probe": {"text": "hello agent"},
            "description": "Low-cost SHA-256 checksum and digest utility for autonomous agents.",
            "price": 0.001,
            "category": "developer-tools/hashing",
        },
        {
            "url": "https://capi2-demand-tools.onrender.com/v1/hash/sha512",
            "name": "capi2 SHA-512",
            "probe": {"text": "hello agent"},
            "description": "Low-cost SHA-512 checksum and digest utility for autonomous agents.",
            "price": 0.001,
            "category": "developer-tools/hashing",
        },
        {
            "url": "https://capi2-demand-tools.onrender.com/v1/base64/encode",
            "name": "capi2 Base64 Encode",
            "probe": {"text": "hello agent"},
            "description": "Low-cost Base64 encoding utility for API payloads and autonomous-agent workflows.",
            "price": 0.001,
            "category": "developer-tools/encoding",
        },
        {
            "url": "https://capi2-demand-tools.onrender.com/v1/base64/decode",
            "name": "capi2 Base64 Decode",
            "probe": {"data": "aGVsbG8gYWdlbnQ=", "urlsafe": False},
            "description": "Low-cost Base64 and Base64URL decoding utility for autonomous-agent workflows.",
            "price": 0.001,
            "category": "developer-tools/encoding",
        },
        {
            "url": "https://capi2-demand-tools.onrender.com/v1/jwt/decode",
            "name": "capi2 JWT Decode",
            "probe": {"token": "eyJhbGciOiJub25lIn0.eyJzdWIiOiIxMjMifQ."},
            "description": "Low-cost JWT header and claims decoding for token inspection and debugging; no signature verification.",
            "price": 0.001,
            "category": "developer-tools/auth",
        },
        {
            "url": "https://capi2-demand-tools.onrender.com/v1/json/canonicalize",
            "name": "capi2 JSON Canonical",
            "probe": {"value": {"b": 2, "a": 1}},
            "description": "Low-cost deterministic JSON canonicalization for stable hashing, signing and comparison.",
            "price": 0.001,
            "category": "developer-tools/json",
        },
    ]


def _run_distribution() -> None:
    # Let uvicorn bind first so external verification probes can reach production.
    time.sleep(20)
    print("directory-distribution: starting one-shot Market402 + 402 Index submissions", flush=True)

    for item in _registrations():
        index_payload = {
            "url": item["url"],
            "name": item["name"],
            "protocol": "x402",
            "http_method": "POST",
            "probe_body": json.dumps(item["probe"]),
            "description": item["description"],
            "price_usd": item["price"],
            "payment_asset": "USDC",
            "payment_network": "Base",
            "category": item["category"],
            "provider": "capi2",
            "contact_email": "capi2@agentmail.to",
        }
        _post_json("https://402index.io/api/v1/register", index_payload, f"402index {item['name']}")

    for item in _registrations():
        status, _ = _post_json("https://market402.com/submit", {"url": item["url"]}, f"market402-json {item['name']}")
        if status in {400, 404, 415, 422}:
            _post_form("https://market402.com/submit", {"url": item["url"]}, f"market402-form {item['name']}")

    print("directory-distribution: one-shot submissions finished", flush=True)


if (
    os.getenv("CAPI2_DIRECTORY_DISTRIBUTE", "false").lower() == "true"
    and _is_claim_verify_process()
):
    threading.Thread(target=_run_distribution, daemon=True).start()
