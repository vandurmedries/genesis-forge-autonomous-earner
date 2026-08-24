"""capi2 x402 runtime compatibility and one-shot directory distribution.

Loaded when the repo root is on PYTHONPATH. It:
- keeps the intelligence lane inside low-cost buyer/router caps by default;
- mirrors canonical x402 v2 PaymentRequired into API 402 JSON bodies while preserving PAYMENT-REQUIRED;
- publishes an explicit machine-readable x402 payment guide and OpenAPI buyer instructions;
- records successful/failing settlements as structured runtime evidence including tx/reference and route;
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
from datetime import datetime, timezone

# Keep the high-intent intelligence tools inside common micro-purchase router caps.
# An explicit Render env var still wins when intentionally configured.
os.environ.setdefault("CAPI2_INTELLIGENCE_TOOL_PRICE", "$0.005")


def _payment_guide_for(title: str) -> dict:
    is_claim = "Claim Verify" in title
    return {
        "protocol": "x402",
        "version": 2,
        "signup_required": False,
        "api_key_required": False,
        "asset": "USDC",
        "network": "eip155:8453",
        "network_name": "Base",
        "headers": {
            "challenge": "PAYMENT-REQUIRED",
            "payment": "PAYMENT-SIGNATURE",
            "settlement": "PAYMENT-RESPONSE",
        },
        "flow": [
            "POST the JSON request without payment.",
            "If HTTP 402 is returned, read/decode PAYMENT-REQUIRED and choose a compatible accepts entry.",
            "Use a funded x402 v2-compatible Base/USDC wallet/client to sign the required exact payment authorization.",
            "Retry the same HTTP method, URL and JSON body with the resulting PAYMENT-SIGNATURE header.",
            "On successful verification, execution and settlement, receive HTTP 2xx and read PAYMENT-RESPONSE for settlement evidence.",
        ],
        "buyer_requirements": [
            "A funded wallet/client that supports x402 v2 exact payments on Base USDC.",
            "Enough USDC for the selected route price.",
            "The ability to retry the same request with PAYMENT-SIGNATURE.",
        ],
        "catalog": (
            "https://capi2-claim-verify.onrender.com/.well-known/x402"
            if is_claim
            else "https://capi2-demand-tools.onrender.com/v1/catalog"
        ),
        "note": "Directory/health probes often stop at 402 by design; only a funded buyer can produce the paid retry and 2xx settlement.",
    }


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

        async def payment_guide():
            return _payment_guide_for(str(getattr(self, "title", "")))

        self.add_api_route(
            "/.well-known/402index-verify.txt",
            verification_file,
            methods=["GET"],
            include_in_schema=False,
            response_class=PlainTextResponse,
        )
        self.add_api_route(
            "/v1/payment-guide",
            payment_guide,
            methods=["GET"],
            tags=["x402", "payment", "buyer guide"],
            summary="How an autonomous buyer completes an x402 payment",
            description=(
                "Machine-readable flow for 402 -> PAYMENT-REQUIRED -> funded Base/USDC signing -> "
                "PAYMENT-SIGNATURE retry -> 2xx + PAYMENT-RESPONSE. No signup or API key is required."
            ),
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
                    "claim verification. No signup or API key is required. Send a public vendor_url and exact "
                    "claim. An unpaid request returns x402 v2 HTTP 402 with PAYMENT-REQUIRED; use a funded "
                    "Base/USDC x402 client to sign the payment, retry the exact request with PAYMENT-SIGNATURE, "
                    "then read PAYMENT-RESPONSE on the successful 2xx for settlement evidence. See /v1/payment-guide."
                )
            elif "Agent Utilities" in title or "Demand Microtools" in title:
                guidance = (
                    "Use the paid POST routes for live public web/API lookup, DNS/RDAP/TLS domain intelligence, "
                    "API/OpenAPI discovery audits, evidence extraction, x402 seller health, or deterministic "
                    "utilities. No signup or API key is required. Each operation publishes its own x402 price "
                    "and input schema. On HTTP 402 read PAYMENT-REQUIRED, sign with a funded Base/USDC x402 v2 "
                    "client, retry the exact request with PAYMENT-SIGNATURE, and read PAYMENT-RESPONSE on 2xx. "
                    "See /v1/payment-guide. Private/reserved network targets are blocked."
                )

            if guidance:
                info = schema.setdefault("info", {})
                info["x-guidance"] = guidance
                info["x-payment-guide"] = "/v1/payment-guide"
                info["x-payment-flow"] = {
                    "challengeHeader": "PAYMENT-REQUIRED",
                    "paymentHeader": "PAYMENT-SIGNATURE",
                    "settlementHeader": "PAYMENT-RESPONSE",
                    "network": "eip155:8453",
                    "asset": "USDC",
                    "signupRequired": False,
                    "apiKeyRequired": False,
                }
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
                        "network": "eip155:8453",
                        "asset": "USDC",
                        "protocols": [{"x402": {"version": 2}}],
                        "challengeHeader": "PAYMENT-REQUIRED",
                        "paymentHeader": "PAYMENT-SIGNATURE",
                        "settlementHeader": "PAYMENT-RESPONSE",
                        "paymentGuide": "/v1/payment-guide",
                    }
                    operation.setdefault("responses", {}).setdefault(
                        "402", {"description": "Payment Required; read PAYMENT-REQUIRED and retry with PAYMENT-SIGNATURE"}
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


def _install_settlement_evidence_logger() -> None:
    """Log route-aware settlement evidence from the SDK's async HTTP settlement boundary."""
    try:
        from x402.http.x402_http_server import x402HTTPResourceServer
    except Exception as exc:
        print(f"x402-settlement-logger: unavailable {type(exc).__name__}: {exc}", flush=True)
        return

    original = x402HTTPResourceServer.process_settlement
    if getattr(original, "_capi2_settlement_logger", False):
        return

    async def wrapped(
        self,
        payment_payload,
        requirements,
        context=None,
        settlement_overrides=None,
        declared_extensions=None,
        transport_context=None,
        *,
        before_handler_settlement=None,
        phase=None,
    ):
        result = await original(
            self,
            payment_payload,
            requirements,
            context=context,
            settlement_overrides=settlement_overrides,
            declared_extensions=declared_extensions,
            transport_context=transport_context,
            before_handler_settlement=before_handler_settlement,
            phase=phase,
        )
        try:
            settle_response = getattr(result, "settle_response", None)
            transaction = getattr(result, "transaction", None) or getattr(settle_response, "transaction", None)
            network = getattr(result, "network", None) or getattr(settle_response, "network", None) or getattr(requirements, "network", None)
            payer = getattr(result, "payer", None) or getattr(settle_response, "payer", None)
            amount_atomic = getattr(settle_response, "amount", None) or getattr(requirements, "amount", None)
            asset = getattr(requirements, "asset", None)
            pay_to = getattr(requirements, "pay_to", None)
            path = getattr(context, "path", None) if context is not None else None
            resource = getattr(getattr(payment_payload, "resource", None), "url", None)
            success = bool(getattr(result, "success", False))
            amount_usdc = None
            if amount_atomic is not None and str(asset).lower() == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913":
                try:
                    amount_usdc = int(str(amount_atomic)) / 1_000_000
                except (TypeError, ValueError):
                    amount_usdc = None
            evidence = {
                "event": "x402_settlement",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "success": success,
                "phase": phase or "after-handler",
                "path": path,
                "resource": resource,
                "transaction": transaction,
                "network": str(network) if network is not None else None,
                "payer": payer,
                "asset": asset,
                "amount_atomic": str(amount_atomic) if amount_atomic is not None else None,
                "amount_usdc": amount_usdc,
                "pay_to": pay_to,
                "error_reason": getattr(result, "error_reason", None) or getattr(settle_response, "error_reason", None),
            }
            print("capi2-settlement: " + json.dumps(evidence, sort_keys=True, separators=(",", ":")), flush=True)
        except Exception as exc:
            print(f"capi2-settlement-log-error: {type(exc).__name__}: {exc}", flush=True)
        return result

    wrapped._capi2_settlement_logger = True
    x402HTTPResourceServer.process_settlement = wrapped
    print("x402-settlement-logger: installed", flush=True)


_install_fastapi_discovery_support()
_install_x402_body_mirror()
_install_settlement_evidence_logger()


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
        headers={"Content-Type": "application/json", "User-Agent": "capi2-directory-distributor/2.2"},
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


def _env_price(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip().lstrip("$")
    try:
        value = float(raw)
        return value if value >= 0 else default
    except (TypeError, ValueError):
        return default


def _registrations() -> list[dict]:
    demand = "https://capi2-demand-tools.onrender.com"
    claim_price = _env_price("CAPI2_CLAIM_VERIFY_PRICE", 0.01)
    intel_price = _env_price("CAPI2_INTELLIGENCE_TOOL_PRICE", 0.005)
    micro_price = _env_price("CAPI2_DEMAND_TOOL_PRICE", 0.001)
    rows = [
        {"url": "https://capi2-claim-verify.onrender.com/v1/claim-verify", "name": "capi2 Claim Verify",
         "probe": {"vendor_url": "https://example.com/security", "claim": "Vendor states that customer data is encrypted at rest."},
         "description": "Evidence-backed vendor claim verification for AI agents and procurement workflows.",
         "price": claim_price, "category": "ai/vendor-risk"},
        {"url": f"{demand}/v1/web/lookup", "name": "capi2 Live Web Lookup",
         "probe": {"url": "https://example.com", "query": "example domain"},
         "description": "Live public web/API lookup with structured metadata and relevant passages.",
         "price": intel_price, "category": "data/web"},
        {"url": f"{demand}/v1/domain/intelligence", "name": "capi2 Domain Intelligence",
         "probe": {"domain": "example.com", "include_rdap": True},
         "description": "DNS, RDAP, HTTPS and TLS intelligence for public domains.",
         "price": intel_price, "category": "data/domain"},
        {"url": f"{demand}/v1/api/audit", "name": "capi2 API Discovery Audit",
         "probe": {"url": "https://capi2-demand-tools.onrender.com"},
         "description": "Audit OpenAPI, x402, agent manifests, robots, llms and health discovery.",
         "price": intel_price, "category": "developer-tools/api-audit"},
        {"url": f"{demand}/v1/evidence/extract", "name": "capi2 Evidence Extract",
         "probe": {"url": "https://example.com", "query": "example domain", "max_passages": 5},
         "description": "Extract and rank relevant evidence passages from a public webpage.",
         "price": intel_price, "category": "data/evidence"},
        {"url": f"{demand}/v1/x402/health", "name": "capi2 Agent x402 Health",
         "probe": {"url": "https://capi2-demand-tools.onrender.com/v1/web/lookup"},
         "description": "x402 and agent seller discovery/health audit without attaching payment.",
         "price": intel_price, "category": "developer-tools/x402"},
        {"url": f"{demand}/v1/hash/sha256", "name": "capi2 SHA-256",
         "probe": {"text": "hello agent"}, "description": "Low-cost SHA-256 checksum utility.",
         "price": micro_price, "category": "developer-tools/hashing"},
        {"url": f"{demand}/v1/hash/sha512", "name": "capi2 SHA-512",
         "probe": {"text": "hello agent"}, "description": "Low-cost SHA-512 checksum utility.",
         "price": micro_price, "category": "developer-tools/hashing"},
        {"url": f"{demand}/v1/base64/encode", "name": "capi2 Base64 Encode",
         "probe": {"text": "hello agent"}, "description": "Low-cost Base64 encoding utility.",
         "price": micro_price, "category": "developer-tools/encoding"},
        {"url": f"{demand}/v1/base64/decode", "name": "capi2 Base64 Decode",
         "probe": {"data": "aGVsbG8gYWdlbnQ=", "urlsafe": False}, "description": "Low-cost Base64 decoding utility.",
         "price": micro_price, "category": "developer-tools/encoding"},
        {"url": f"{demand}/v1/jwt/decode", "name": "capi2 JWT Decode",
         "probe": {"token": "eyJhbGciOiJub25lIn0.eyJzdWIiOiIxMjMifQ."}, "description": "JWT claims inspection without verification.",
         "price": micro_price, "category": "developer-tools/auth"},
        {"url": f"{demand}/v1/json/canonicalize", "name": "capi2 JSON Canonical",
         "probe": {"value": {"b": 2, "a": 1}}, "description": "Deterministic JSON canonicalization.",
         "price": micro_price, "category": "developer-tools/json"},
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
