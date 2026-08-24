"""capi2 x402 runtime compatibility and one-shot directory distribution.

When this file is on PYTHONPATH it:
1. Mirrors the canonical x402 v2 PaymentRequired object into empty API 402 JSON
   bodies while preserving the SDK-generated PAYMENT-REQUIRED header.
2. Adds a temporary .well-known route used for 402 Index domain verification.
3. Can run explicitly gated, one-shot free directory actions.

CAPI2_DIRECTORY_DISTRIBUTE modes:
- all/true: submit to 402 Index and Market402
- market402: submit only to Market402
- 402claim: claim and verify the current Render service hostname on 402 Index
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


def _install_402index_verify_route() -> None:
    try:
        from fastapi import FastAPI
        from fastapi.responses import PlainTextResponse
    except Exception:
        return

    original = FastAPI.__init__
    if getattr(original, "_capi2_402index_route", False):
        return

    def patched(self, *args, **kwargs):
        original(self, *args, **kwargs)

        async def verification_file():
            value = os.getenv("CAPI2_402INDEX_VERIFY_HASH", "").strip()
            if not value:
                return PlainTextResponse("not configured\n", status_code=404)
            return PlainTextResponse(value + "\n", status_code=200)

        self.add_api_route(
            "/.well-known/402index-verify.txt",
            verification_file,
            methods=["GET"],
            include_in_schema=False,
            response_class=PlainTextResponse,
        )

    patched._capi2_402index_route = True
    FastAPI.__init__ = patched


def _install_x402_body_mirror() -> None:
    if os.getenv("CAPI2_MIRROR_X402_BODY", "true").lower() != "true":
        return
    try:
        from x402.http.x402_http_server_base import x402HTTPServerBase
    except Exception as exc:
        # During Render's dependency-install phase x402 may not exist yet. Runtime
        # imports sitecustomize again after the venv is ready, where this succeeds.
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
        if response.status == 402 and not is_web_browser and (response.body is None or response.body == {}):
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


_install_402index_verify_route()
_install_x402_body_mirror()


def _service_domain() -> str | None:
    argv = " ".join(str(arg) for arg in sys.argv)
    if "capi2.x402_service.app:app" in argv:
        return "capi2-claim-verify.onrender.com"
    if "capi2.demand_tools.app:app" in argv:
        return "capi2-demand-tools.onrender.com"
    return None


def _post_json(url: str, payload: dict, label: str, *, redact: bool = False) -> tuple[int | None, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "capi2-directory-distributor/1.2"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
            shown = "<redacted successful response>" if redact else body[:1800]
            print(f"directory-distribution {label}: HTTP {response.status} {shown}", flush=True)
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        shown = "<redacted error response>" if redact else body[:1800]
        print(f"directory-distribution {label}: HTTP {exc.code} {shown}", flush=True)
        return exc.code, body
    except Exception as exc:
        print(f"directory-distribution {label}: ERROR {type(exc).__name__}: {exc}", flush=True)
        return None, ""


def _registrations() -> list[dict]:
    return [
        {"url": "https://capi2-claim-verify.onrender.com/v1/claim-verify", "name": "capi2 Claim Verify", "probe": {"vendor_url": "https://example.com/security", "claim": "Vendor states that customer data is encrypted at rest."}, "description": "Evidence-backed vendor claim verification for AI agents, procurement, due diligence, RFP and security workflows.", "price": 0.01, "category": "ai/vendor-risk"},
        {"url": "https://capi2-demand-tools.onrender.com/v1/hash/sha256", "name": "capi2 SHA-256", "probe": {"text": "hello agent"}, "description": "Low-cost SHA-256 checksum and digest utility for autonomous agents.", "price": 0.001, "category": "developer-tools/hashing"},
        {"url": "https://capi2-demand-tools.onrender.com/v1/hash/sha512", "name": "capi2 SHA-512", "probe": {"text": "hello agent"}, "description": "Low-cost SHA-512 checksum and digest utility for autonomous agents.", "price": 0.001, "category": "developer-tools/hashing"},
        {"url": "https://capi2-demand-tools.onrender.com/v1/base64/encode", "name": "capi2 Base64 Encode", "probe": {"text": "hello agent"}, "description": "Low-cost Base64 encoding utility for API payloads and autonomous-agent workflows.", "price": 0.001, "category": "developer-tools/encoding"},
        {"url": "https://capi2-demand-tools.onrender.com/v1/base64/decode", "name": "capi2 Base64 Decode", "probe": {"data": "aGVsbG8gYWdlbnQ=", "urlsafe": False}, "description": "Low-cost Base64 and Base64URL decoding utility for autonomous-agent workflows.", "price": 0.001, "category": "developer-tools/encoding"},
        {"url": "https://capi2-demand-tools.onrender.com/v1/jwt/decode", "name": "capi2 JWT Decode", "probe": {"token": "eyJhbGciOiJub25lIn0.eyJzdWIiOiIxMjMifQ."}, "description": "Low-cost JWT header and claims decoding for token inspection and debugging; no signature verification.", "price": 0.001, "category": "developer-tools/auth"},
        {"url": "https://capi2-demand-tools.onrender.com/v1/json/canonicalize", "name": "capi2 JSON Canonical", "probe": {"value": {"b": 2, "a": 1}}, "description": "Low-cost deterministic JSON canonicalization for stable hashing, signing and comparison.", "price": 0.001, "category": "developer-tools/json"},
    ]


def _submit_402index() -> None:
    for item in _registrations():
        payload = {
            "url": item["url"], "name": item["name"], "protocol": "x402", "http_method": "POST",
            "probe_body": json.dumps(item["probe"]), "description": item["description"], "price_usd": item["price"],
            "payment_asset": "USDC", "payment_network": "Base", "category": item["category"],
            "provider": "capi2", "contact_email": "capi2@agentmail.to",
        }
        _post_json("https://402index.io/api/v1/register", payload, f"402index {item['name']}")


def _submit_market402() -> None:
    for item in _registrations():
        _post_json("https://market402.com/submit", {"resource": item["url"]}, f"market402 {item['name']}")


def _claim_402index_domain(domain: str) -> None:
    status, body = _post_json(
        "https://402index.io/api/v1/claim",
        {"domain": domain, "contact_email": "capi2@agentmail.to"},
        f"402index-claim {domain}",
        redact=True,
    )
    if status not in {200, 201}:
        return
    try:
        result = json.loads(body)
        verification_hash = str(result["verification_hash"]).strip()
    except Exception as exc:
        print(f"directory-distribution 402index-claim {domain}: invalid response {type(exc).__name__}", flush=True)
        return

    # The .well-known FastAPI route reads this dynamically from the process env.
    # The raw verification token is deliberately not logged or persisted.
    os.environ["CAPI2_402INDEX_VERIFY_HASH"] = verification_hash
    time.sleep(2)

    verify_status, verify_body = _post_json(
        "https://402index.io/api/v1/claim/verify",
        {"domain": domain},
        f"402index-verify {domain}",
    )
    if verify_status == 200:
        try:
            result = json.loads(verify_body)
            print(
                f"directory-distribution 402index-domain-verified: domain={domain} services_count={result.get('services_count')}",
                flush=True,
            )
        except Exception:
            pass


def _run_distribution(mode: str) -> None:
    # Let the production server bind before any external verifier fetches .well-known.
    time.sleep(20)
    print(f"directory-distribution: starting one-shot mode={mode}", flush=True)
    if mode in {"true", "all"}:
        _submit_402index()
        _submit_market402()
    elif mode == "market402":
        _submit_market402()
    elif mode == "402claim":
        domain = _service_domain()
        if domain:
            _claim_402index_domain(domain)
    print(f"directory-distribution: one-shot mode={mode} finished", flush=True)


_mode = os.getenv("CAPI2_DIRECTORY_DISTRIBUTE", "false").lower()
if _mode in {"true", "all", "market402", "402claim"} and _service_domain():
    threading.Thread(target=_run_distribution, args=(_mode,), daemon=True).start()
