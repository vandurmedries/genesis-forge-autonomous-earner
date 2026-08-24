"""capi2 x402 runtime compatibility and one-shot directory distribution.

Loaded when the repo root is on PYTHONPATH. It:
- mirrors canonical x402 v2 PaymentRequired into API 402 JSON bodies while preserving PAYMENT-REQUIRED;
- enriches FastAPI OpenAPI with x402scan-style discovery metadata;
- exposes a temporary 402 Index domain-verification route;
- runs explicitly gated one-shot free directory submissions/claims.

CAPI2_DIRECTORY_DISTRIBUTE modes: false, all/true, market402, 402claim.
No payment is attempted by this hook.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request


def _install_fastapi_discovery_support() -> None:
    try:
        from fastapi import FastAPI
        from fastapi.responses import PlainTextResponse
    except Exception:
        return

    original = FastAPI.__init__
    if getattr(original, "_capi2_discovery_support", False):
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

        original_openapi = self.openapi

        def enhanced_openapi():
            if self.openapi_schema is not None:
                return self.openapi_schema

            schema = original_openapi()
            title = str(getattr(self, "title", ""))
            guidance = None
            if "Claim Verify" in title:
                guidance = (
                    "Use POST /v1/claim-verify for evidence-backed vendor/product/security/procurement "
                    "claim verification. Send a public vendor_url and exact claim. Unpaid calls return "
                    "x402 v2 402; pay USDC on Base and retry for evidence, verdict and confidence."
                )
            elif "Agent Utilities" in title or "Demand Microtools" in title:
                guidance = (
                    "Use the paid POST routes for live public web/API lookup, DNS/RDAP/TLS domain "
                    "intelligence, API/OpenAPI discovery audits, evidence extraction, x402 seller health, "
                    "or deterministic hashing/encoding/JWT/JSON utilities. Each operation publishes its "
                    "own x402 price and input schema. Private/reserved network targets are blocked."
                )

            if guidance:
                info = schema.setdefault("info", {})
                info["x-guidance"] = guidance
                info.setdefault("contact", {})["email"] = "capi2@agentmail.to"

                for path_item in schema.get("paths", {}).values():
                    if not isinstance(path_item, dict):
                        continue
                    operation = path_item.get("post")
                    if not isinstance(operation, dict):
                        continue
                    raw_price = operation.get("x-x402-price") or operation.get("x-price")
                    if not raw_price:
                        continue
                    amount = str(raw_price).lstrip("$")
                    operation["x-payment-info"] = {
                        "price": {"mode": "fixed", "currency": "USD", "amount": amount},
                        "protocols": [{"x402": {}}],
                    }
                    operation.setdefault("responses", {}).setdefault(
                        "402", {"description": "Payment Required"}
                    )

                self.openapi_schema = schema
            return schema

        self.openapi = enhanced_openapi

    patched._capi2_discovery_support = True
    FastAPI.__init__ = patched


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
        response = original(self, payment_required, is_web_browser, paywall_config, custom_html, unpaid_response)
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


_install_fastapi_discovery_support()
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
        headers={"Content-Type": "application/json", "User-Agent": "capi2-directory-distributor/2.0"},
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
    demand = "https://capi2-demand-tools.onrender.com"
    rows = [
        {"url": "https://capi2-claim-verify.onrender.com/v1/claim-verify", "name": "capi2 Claim Verify",
         "probe": {"vendor_url": "https://example.com/security", "claim": "Vendor states that customer data is encrypted at rest."},
         "description": "Evidence-backed vendor claim verification for AI agents and procurement workflows.",
         "price": 0.01, "category": "ai/vendor-risk"},
        {"url": f"{demand}/v1/web/lookup", "name": "capi2 Live Web Lookup",
         "probe": {"url": "https://example.com", "query": "example domain"},
         "description": "Live public web/API lookup with structured metadata and relevant passages.",
         "price": 0.01, "category": "data/web"},
        {"url": f"{demand}/v1/domain/intelligence", "name": "capi2 Domain Intelligence",
         "probe": {"domain": "example.com", "include_rdap": True},
         "description": "DNS, RDAP, HTTPS and TLS intelligence for public domains.",
         "price": 0.01, "category": "data/domain"},
        {"url": f"{demand}/v1/api/audit", "name": "capi2 API Discovery Audit",
         "probe": {"url": "https://capi2-demand-tools.onrender.com"},
         "description": "Audit OpenAPI, x402, agent manifests, robots, llms and health discovery.",
         "price": 0.01, "category": "developer-tools/api-audit"},
        {"url": f"{demand}/v1/evidence/extract", "name": "capi2 Evidence Extract",
         "probe": {"url": "https://example.com", "query": "example domain", "max_passages": 5},
         "description": "Extract and rank relevant evidence passages from a public webpage.",
         "price": 0.01, "category": "data/evidence"},
        {"url": f"{demand}/v1/x402/health", "name": "capi2 Agent x402 Health",
         "probe": {"url": "https://capi2-demand-tools.onrender.com/v1/web/lookup"},
         "description": "x402 and agent seller discovery/health audit without attaching payment.",
         "price": 0.01, "category": "developer-tools/x402"},
        {"url": f"{demand}/v1/hash/sha256", "name": "capi2 SHA-256",
         "probe": {"text": "hello agent"}, "description": "Low-cost SHA-256 checksum utility.",
         "price": 0.001, "category": "developer-tools/hashing"},
        {"url": f"{demand}/v1/hash/sha512", "name": "capi2 SHA-512",
         "probe": {"text": "hello agent"}, "description": "Low-cost SHA-512 checksum utility.",
         "price": 0.001, "category": "developer-tools/hashing"},
        {"url": f"{demand}/v1/base64/encode", "name": "capi2 Base64 Encode",
         "probe": {"text": "hello agent"}, "description": "Low-cost Base64 encoding utility.",
         "price": 0.001, "category": "developer-tools/encoding"},
        {"url": f"{demand}/v1/base64/decode", "name": "capi2 Base64 Decode",
         "probe": {"data": "aGVsbG8gYWdlbnQ=", "urlsafe": False}, "description": "Low-cost Base64 decoding utility.",
         "price": 0.001, "category": "developer-tools/encoding"},
        {"url": f"{demand}/v1/jwt/decode", "name": "capi2 JWT Decode",
         "probe": {"token": "eyJhbGciOiJub25lIn0.eyJzdWIiOiIxMjMifQ."}, "description": "JWT claims inspection without verification.",
         "price": 0.001, "category": "developer-tools/auth"},
        {"url": f"{demand}/v1/json/canonicalize", "name": "capi2 JSON Canonical",
         "probe": {"value": {"b": 2, "a": 1}}, "description": "Deterministic JSON canonicalization.",
         "price": 0.001, "category": "developer-tools/json"},
    ]
    return rows


def _submit_402index() -> None:
    for item in _registrations():
        payload = {
            "url": item["url"], "name": item["name"], "protocol": "x402", "http_method": "POST",
            "probe_body": json.dumps(item["probe"]), "description": item["description"],
            "price_usd": item["price"], "payment_asset": "USDC", "payment_network": "Base",
            "category": item["category"], "provider": "capi2", "contact_email": "capi2@agentmail.to",
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
        verification_hash = str(json.loads(body)["verification_hash"]).strip()
    except Exception as exc:
        print(f"directory-distribution 402index-claim {domain}: invalid response {type(exc).__name__}", flush=True)
        return

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
