"""Demand-tools runtime patch loaded ahead of the repository usercustomize.

Keeps x402's native settlement path intact, adds official lifecycle-hook
observability, disables repeated Agent402 self-registration by default, and
makes the paid /v1/x402/health purchase semantics unambiguous.
"""
from __future__ import annotations

import functools
import inspect
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

os.environ.setdefault("CAPI2_AGENT402_REGISTER", "false")

PUBLIC_ORIGIN = os.getenv("CAPI2_DEMAND_TOOLS_ORIGIN", "https://capi2-demand-tools.onrender.com").rstrip("/")
BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
HEALTH_SUMMARY = "Paid x402 seller health audit"
HEALTH_DESCRIPTION = (
    "Paid capi2 audit of public x402 and agent discovery surfaces. "
    "This capi2 endpoint itself requires its published x402 payment; it never "
    "pays or executes the target seller's paid operation."
)


def plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return plain(value.model_dump(by_alias=True, exclude_none=True, mode="json"))
        except TypeError:
            return plain(value.model_dump(by_alias=True, exclude_none=True))
    if hasattr(value, "dict"):
        return plain(value.dict())
    return str(value)


def first(mapping: Any, *keys: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def deep_first(value: Any, *keys: str) -> Any:
    if isinstance(value, dict):
        direct = first(value, *keys)
        if direct not in (None, ""):
            return direct
        for nested in value.values():
            found = deep_first(nested, *keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for nested in value:
            found = deep_first(nested, *keys)
            if found not in (None, ""):
                return found
    return None


def resource_url(value: Any) -> str | None:
    value = plain(value)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        nested = first(value, "url", "resource", "endpoint")
        return str(nested) if nested not in (None, "") else None
    return None


def amount_usdc(amount: Any, asset: Any) -> float | None:
    if amount in (None, ""):
        return None
    try:
        value = Decimal(str(amount).strip().replace("$", ""))
    except (InvalidOperation, ValueError):
        return None
    if str(asset or "").lower() in {BASE_USDC, "usdc"}:
        if value == value.to_integral_value() and value >= 1:
            value /= Decimal(1_000_000)
        return float(value)
    if Decimal(0) <= value < Decimal(1):
        return float(value)
    return None


def event_fields(ctx: Any) -> dict[str, Any]:
    requirements = plain(getattr(ctx, "requirements", None)) or {}
    payload = plain(getattr(ctx, "payment_payload", None)) or {}
    result = plain(getattr(ctx, "result", None)) or {}
    transport = plain(getattr(ctx, "transport_context", None)) or {}

    resource = resource_url(first(requirements, "resource", "url")) or resource_url(first(payload, "resource", "url"))
    path = None
    if resource:
        path = resource[len(PUBLIC_ORIGIN):] or "/" if resource.startswith(PUBLIC_ORIGIN) else resource
    if not path:
        path = deep_first(transport, "path")

    asset = first(requirements, "asset") or deep_first(result, "asset")
    amount = first(requirements, "amount", "max_amount_required", "maxAmountRequired", "price")
    payer = deep_first(result, "payer", "from", "sender") or deep_first(payload, "payer", "from", "sender")
    network = first(requirements, "network") or deep_first(result, "network") or first(payload, "network")
    transaction = deep_first(result, "transaction", "transaction_hash", "tx_hash", "txHash")

    out = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "path": path,
        "resource": resource,
        "amount_atomic": str(amount) if amount not in (None, "") else None,
        "amount_usdc": amount_usdc(amount, asset),
        "transaction": transaction,
        "network": str(network) if network not in (None, "") else None,
        "payer": payer,
        "asset": asset,
    }
    return {k: v for k, v in out.items() if v is not None}


def log(prefix: str, payload: dict[str, Any]) -> None:
    print(prefix + json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str), flush=True)


def install_hooks(server: Any) -> None:
    if getattr(server, "_capi2_demand_hooks", False):
        return

    def after_verify(ctx: Any) -> None:
        data = event_fields(ctx)
        result = plain(getattr(ctx, "result", None)) or {}
        data.update({"event": "x402_verify_result", "success": bool(first(result, "is_valid", "isValid", "valid") or deep_first(result, "is_valid", "isValid"))})
        if not data["success"] and deep_first(result, "invalid_reason", "invalidReason"):
            data["error_reason"] = deep_first(result, "invalid_reason", "invalidReason")
        log("capi2-payment-attempt: ", data)

    def verify_failure(ctx: Any) -> None:
        data = event_fields(ctx)
        error = getattr(ctx, "error", None)
        data.update({"event": "x402_verify_failure", "success": False})
        if error is not None:
            data["error_type"] = type(error).__name__
            data["error"] = str(error)[:500]
        log("capi2-payment-attempt: ", data)
        return None

    def after_settle(ctx: Any) -> None:
        data = event_fields(ctx)
        result = plain(getattr(ctx, "result", None)) or {}
        data.update({"event": "x402_settlement", "success": bool(first(result, "success") if isinstance(result, dict) else False)})
        log("capi2-settlement: ", data)

    def settle_failure(ctx: Any) -> None:
        data = event_fields(ctx)
        error = getattr(ctx, "error", None)
        data.update({"event": "x402_settlement", "success": False})
        if error is not None:
            data["error_type"] = type(error).__name__
            data["error"] = str(error)[:500]
        log("capi2-settlement: ", data)
        return None

    def canceled(ctx: Any) -> None:
        data = event_fields(ctx)
        data.update({"event": "x402_verified_payment_canceled", "success": False, "reason": getattr(ctx, "reason", None)})
        log("capi2-payment-attempt: ", data)
        return None

    if hasattr(server, "on_after_verify"):
        server.on_after_verify(after_verify)
    if hasattr(server, "on_verify_failure"):
        server.on_verify_failure(verify_failure)
    server.on_after_settle(after_settle)
    if hasattr(server, "on_settle_failure"):
        server.on_settle_failure(settle_failure)
    if hasattr(server, "on_verified_payment_canceled"):
        server.on_verified_payment_canceled(canceled)
    server._capi2_demand_hooks = True
    print("capi2-demand-hooks: installed", flush=True)


def payment_metadata() -> dict[str, Any]:
    return {
        "protocol": "x402",
        "version": 2,
        "network": os.getenv("CAPI2_X402_NETWORK", "eip155:8453"),
        "asset": "USDC",
        "challenge_header": "PAYMENT-REQUIRED",
        "payment_header": "PAYMENT-SIGNATURE",
        "settlement_header": "PAYMENT-RESPONSE",
        "guide": "/v1/payment-guide",
    }


def enrich(value: Any) -> Any:
    if isinstance(value, list):
        return [enrich(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {k: enrich(v) for k, v in value.items()}
    resource = str(out.get("resource", ""))
    endpoint = str(out.get("endpoint", ""))
    if out.get("price") and (resource.startswith(PUBLIC_ORIGIN + "/v1/") or endpoint.startswith("POST /v1/")):
        out["payment_required"] = True
        out["payment"] = payment_metadata()
        if resource.endswith("/v1/x402/health") or endpoint == "POST /v1/x402/health":
            out["summary"] = HEALTH_SUMMARY
            out["description"] = HEALTH_DESCRIPTION
            out["target_payments_attempted"] = False
    return out


try:
    from x402.http.x402_http_server import x402HTTPResourceServer
except ModuleNotFoundError as exc:
    if exc.name and (exc.name == "x402" or exc.name.startswith("x402.")):
        print("capi2-demand-runtime: deferred until x402 is installed", flush=True)
    else:
        raise
else:
    current = x402HTTPResourceServer.process_settlement
    if getattr(current, "_capi2_settlement_logger", False):
        native = inspect.getclosurevars(current).nonlocals.get("original")
        if not callable(native):
            raise RuntimeError("cannot recover native x402 process_settlement")
        x402HTTPResourceServer.process_settlement = native
        current = native
    signature = inspect.signature(current)
    if not {"self", "payment_payload", "requirements"}.issubset(signature.parameters):
        raise RuntimeError(f"unexpected native x402 process_settlement signature: {signature}")
    print(f"capi2-demand-runtime: native settlement active signature={signature}", flush=True)

    from x402.server import x402ResourceServer

    original_register = x402ResourceServer.register
    if not getattr(original_register, "_capi2_demand_hook_patch", False):
        @functools.wraps(original_register)
        def register_patched(self: Any, *args: Any, **kwargs: Any):
            result = original_register(self, *args, **kwargs)
            install_hooks(self)
            return result

        register_patched._capi2_demand_hook_patch = True
        x402ResourceServer.register = register_patched

    try:
        from fastapi import FastAPI

        original_add_route = FastAPI.add_api_route
        if not getattr(original_add_route, "_capi2_demand_route_patch", False):
            def add_route_patched(self: Any, path: str, endpoint: Any, *args: Any, **kwargs: Any):
                if path == "/v1/x402/health":
                    kwargs["summary"] = HEALTH_SUMMARY
                    kwargs["description"] = HEALTH_DESCRIPTION
                if path in {"/", "/.well-known/x402", "/v1/catalog"} and not getattr(endpoint, "_capi2_enriched", False):
                    if inspect.iscoroutinefunction(endpoint):
                        @functools.wraps(endpoint)
                        async def wrapped(*ep_args: Any, __endpoint=endpoint, **ep_kwargs: Any):
                            return enrich(await __endpoint(*ep_args, **ep_kwargs))
                    else:
                        @functools.wraps(endpoint)
                        def wrapped(*ep_args: Any, __endpoint=endpoint, **ep_kwargs: Any):
                            return enrich(__endpoint(*ep_args, **ep_kwargs))
                    wrapped._capi2_enriched = True
                    endpoint = wrapped
                return original_add_route(self, path, endpoint, *args, **kwargs)

            add_route_patched._capi2_demand_route_patch = True
            FastAPI.add_api_route = add_route_patched

        original_add_middleware = FastAPI.add_middleware
        if not getattr(original_add_middleware, "_capi2_demand_middleware_patch", False):
            def add_middleware_patched(self: Any, middleware_class: Any, *args: Any, **kwargs: Any):
                if getattr(middleware_class, "__name__", "") == "PaymentMiddlewareASGI":
                    routes = kwargs.get("routes")
                    if isinstance(routes, dict):
                        for key, config in list(routes.items()):
                            if str(key).endswith(" /v1/x402/health"):
                                try:
                                    config.description = HEALTH_DESCRIPTION
                                except Exception:
                                    if hasattr(config, "model_copy"):
                                        routes[key] = config.model_copy(update={"description": HEALTH_DESCRIPTION})
                return original_add_middleware(self, middleware_class, *args, **kwargs)

            add_middleware_patched._capi2_demand_middleware_patch = True
            FastAPI.add_middleware = add_middleware_patched
    except Exception as exc:
        print(f"capi2-demand-runtime: FastAPI patch error {type(exc).__name__}:{exc}", flush=True)
