"""capi2 x402 runtime compatibility and one-shot directory distribution.

When this file is on PYTHONPATH it makes API-style HTTP 402 responses mirror the
canonical x402 v2 PaymentRequired object into the JSON response body while
preserving the SDK-generated PAYMENT-REQUIRED header. This improves compatibility
with independent crawlers that inspect the body as well as the canonical header.

Optional distribution modes via CAPI2_DIRECTORY_DISTRIBUTE:
- all/true: submit to 402 Index and Market402
- market402: submit only to Market402
No payment is ever attempted by this hook.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request


def _install_x402_body_mirror() -> None:
    if os.getenv("CAPI2_MIRROR_X402_BODY", "true").lower() != "true":
        return
    try:
        from x402.http.x402_http_server_base import x402HTTPServerBase
    except Exception as exc:
        print(f"x402-body-mirror: unavailable {type(exc).__name__}: {exc}", flush=True)
        return

    original = x402HTTPServerBase._create_http_response
    if getattr(original, "_capi2_body_mirror", False):
        return

    def wrapped(self, payment_required, is_web_browser, paywall_config=None, custom_html=None, unpaid_response=None):
        response = original(
            self,
            payment_required,
            is_web_browser,
            paywall_config,
            custom_html,
            unpaid_response,
        )
        if (
            response.status == 402
            and not is_web_browser
            and (response.body is None or response.body == {})
        ):
            try:
                if hasattr(payment_required, "model_dump"):
                    response.body = payment_required.model_dump(by_alias=True, exclude_none=True)
                elif isinstance(payment_required, dict):
                    response.body = dict(payment_required)
            except Exception as exc:
                print(f"x402-body-mirror: serialize error {type(exc).__name__}: {exc}", flush=True)
        return response

    wrapped._capi2_body_mirror = True
    x402HTTPServerBase._create_http_response = wrapped
    print("x402-body-mirror: installed", flush=True)


_install_x402_body_mirror()


def _is_claim_verify_process() -> bool:
    return any("capi2.x402_service.app:app" in str(arg) for arg in sys.argv)


def _post_json(url: str, payload: dict, label: str) -> tuple[int | None, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "capi2-directory-distributor/1.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
            print(f"directory-distribution {label}: HTTP {response.status} {body[:1800]}", flush=True)
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        print(f"directory-distribution {label}: HTTP {exc.code} {body[:1800]}", flush=True)
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


def _submit_402index() -> None:
    for item in _registrations():
        payload = {
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
        _post_json("https://402index.io/api/v1/register", payload, f"402index {item['name']}")


def _submit_market402() -> None:
    for item in _registrations():
        _post_json(
            "https://market402.com/submit",
            {"resource": item["url"]},
            f"market402 {item['name']}",
        )


def _run_distribution(mode: str) -> None:
    time.sleep(20)
    print(f"directory-distribution: starting one-shot mode={mode}", flush=True)
    if mode in {"true", "all"}:
        _submit_402index()
        _submit_market402()
    elif mode == "market402":
        _submit_market402()
    print(f"directory-distribution: one-shot mode={mode} finished", flush=True)


_mode = os.getenv("CAPI2_DIRECTORY_DISTRIBUTE", "false").lower()
if _mode in {"true", "all", "market402"} and _is_claim_verify_process():
    threading.Thread(target=_run_distribution, args=(_mode,), daemon=True).start()
