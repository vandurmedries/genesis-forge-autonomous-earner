"""Narrow Python startup compatibility + demand-tools x402 observability.

The repository sitecustomize installs an older route-aware settlement wrapper.
With x402 2.20.x that wrapper has an incompatible call shape, so this hook first
restores the native SDK method before any FastAPI app is imported.

For the capi2 demand-tools service only, this module also:
- disables automatic Agent402 self-registration by default;
- attaches settlement evidence through official x402 lifecycle hooks instead of
  wrapping process_settlement;
- logs only paid retries that actually include a payment header, without logging
  the signature itself;
- makes the machine-readable purchase flow explicit and removes the ambiguous
  "without paying" wording from the paid /v1/x402/health route.

During Render build-tool startup x402 may not be installed yet; that case is
expected and ignored.
"""
from __future__ import annotations

import functools
import hashlib
import inspect
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

_DEMAND_TOOLS_RUNTIME = "capi2.demand_tools.app:app" in " ".join(str(arg) for arg in sys.argv)
_BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
_HEALTH_DESCRIPTION = (
    "Paid capi2 audit of public x402 and agent discovery surfaces. "
    "This endpoint itself requires its published x402 payment; it never pays or "
    "executes the target seller's paid operation."
)
_HEALTH_SUMMARY = "Paid x402 seller health audit"

if _DEMAND_TOOLS_RUNTIME:
    # A stable Agent402 seed request is preferred over retrying the capped
    # public self-registration pool on every restart.
    os.environ.setdefault("CAPI2_AGENT402_REGISTER", "false")


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "model_dump"):
        try:
            return _plain(value.model_dump(by_alias=True, exclude_none=True, mode="json"))
        except TypeError:
            return _plain(value.model_dump(by_alias=True, exclude_none=True))
    if hasattr(value, "dict"):
        return _plain(value.dict())
    return str(value)


def _first(mapping: Any, *keys: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _deep_first(value: Any, *keys: str) -> Any:
    if isinstance(value, dict):
        direct = _first(value, *keys)
        if direct not in (None, ""):
            return direct
        for nested in value.values():
            found = _deep_first(nested, *keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _deep_first(nested, *keys)
            if found not in (None, ""):
                return found
    return None


def _resource_url(value: Any) -> str | None:
    value = _plain(value)
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        nested = _first(value, "url", "resource", "endpoint")
        return str(nested) if nested not in (None, "") else None
    return None


def _amount_usdc(amount: Any, asset: Any) -> float | None:
    if amount in (None, ""):
        return None
    raw = str(amount).strip().replace("$", "")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    asset_text = str(asset or "").lower()
    if asset_text in {_BASE_USDC, "usdc"}:
        # x402 PaymentRequirements normally carries ERC-20 amount in atomic
        # units. Preserve already-human decimal values when present.
        if value == value.to_integral_value() and value >= 1:
            value = value / Decimal(1_000_000)
        return float(value)
    if Decimal(0) <= value < Decimal(1):
        return float(value)
    return None


def _settlement_evidence(ctx: Any, *, force_success: bool | None = None) -> dict[str, Any]:
    requirements = _plain(getattr(ctx, "requirements", None)) or {}
    payload = _plain(getattr(ctx, "payment_payload", None)) or {}
    result = _plain(getattr(ctx, "result", None)) or {}

    resource = _resource_url(_first(requirements, "resource", "url"))
    if not resource:
        resource = _resource_url(_first(payload, "resource", "url"))
    public_origin = os.getenv("CAPI2_DEMAND_TOOLS_ORIGIN", "https://capi2-demand-tools.onrender.com").rstrip("/")
    path = None
    if resource:
        path = resource[len(public_origin):] or "/" if resource.startswith(public_origin) else resource

    transaction = _deep_first(result, "transaction", "transaction_hash", "tx_hash", "txHash")
    payer = _deep_first(result, "payer", "from", "sender") or _deep_first(payload, "payer", "from", "sender")
    network = _first(requirements, "network") or _deep_first(result, "network") or _first(payload, "network")
    asset = _first(requirements, "asset") or _deep_first(result, "asset")
    amount_atomic = _first(requirements, "amount", "max_amount_required", "maxAmountRequired", "price")
    raw_success = _deep_first(result, "success")
    success = force_success if force_success is not None else bool(raw_success)

    event = {
        "event": "x402_settlement",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": success,
        "path": path,
        "resource": resource,
        "amount_atomic": str(amount_atomic) if amount_atomic not in (None, "") else None,
        "amount_usdc": _amount_usdc(amount_atomic, asset),
        "transaction": transaction,
        "network": str(network) if network not in (None, "") else None,
        "payer": payer,
        "asset": asset,
    }
    return {key: value for key, value in event.items() if value is not None}


def _install_demand_settlement_hooks(server: Any) -> None:
    if getattr(server, "_capi2_safe_settlement_evidence", False):
        return

    def after_settle(ctx: Any) -> None:
        try:
            print(
                "capi2-settlement: " + json.dumps(_settlement_evidence(ctx), sort_keys=True, separators=(",", ":"), default=str),
                flush=True,
            )
        except Exception as exc:
            print(f"capi2-settlement-log-error: after_settle:{type(exc).__name__}:{exc}", flush=True)

    def settle_failure(ctx: Any) -> None:
        try:
            event = _settlement_evidence(ctx, force_success=False)
            error = getattr(ctx, "error", None)
            if error is not None:
                event["error_type"] = type(error).__name__
                event["error"] = str(error)[:500]
            print(
                "capi2-settlement: " + json.dumps(event, sort_keys=True, separators=(",", ":"), default=str),
                flush=True,
            )
        except Exception as exc:
            print(f"capi2-settlement-log-error: settle_failure:{type(exc).__name__}:{exc}", flush=True)
        return None

    server.on_after_settle(after_settle)
    if hasattr(server, "on_settle_failure"):
        server.on_settle_failure(settle_failure)
    server._capi2_safe_settlement_evidence = True
    print("capi2-safe-settlement-observer: installed", flush=True)


def _payment_metadata() -> dict[str, Any]:
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


def _enrich_catalog_payload(value: Any) -> Any:
    if isinstance(value, list):
        return [_enrich_catalog_payload(item) for item in value]
    if not isinstance(value, dict):
        return value

    enriched = {key: _enrich_catalog_payload(item) for key, item in value.items()}
    resource = str(enriched.get("resource", ""))
    endpoint = str(enriched.get("endpoint", ""))
    looks_like_paid_tool = bool(enriched.get("price")) and (
        resource.startswith("https://capi2-demand-tools.onrender.com/v1/") or endpoint.startswith("POST /v1/")
    )
    if looks_like_paid_tool:
        enriched["payment_required"] = True
        enriched["payment"] = _payment_metadata()
        if resource.endswith("/v1/x402/health") or endpoint == "POST /v1/x402/health":
            enriched["summary"] = _HEALTH_SUMMARY
            enriched["description"] = _HEALTH_DESCRIPTION
            enriched["target_payments_attempted"] = False
    return enriched


class _PaymentAttemptObserverASGI:
    """Log only requests that include an x402 payment proof header."""

    def __init__(self, app: Any, paid_paths: list[str] | tuple[str, ...] | set[str]):
        self.app = app
        self.paid_paths = set(paid_paths)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") not in self.paid_paths:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): val.decode("latin-1", "replace")
            for key, val in scope.get("headers", [])
        }
        payment_header = "payment-signature" if headers.get("payment-signature") else (
            "x-payment" if headers.get("x-payment") else None
        )
        if not payment_header:
            await self.app(scope, receive, send)
            return

        status_code: int | None = None

        async def send_wrapped(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 0))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapped)
        finally:
            client = scope.get("client") or (None, None)
            client_ip = client[0] if isinstance(client, (tuple, list)) and client else None
            client_ref = None
            if client_ip:
                client_ref = "client_" + hashlib.sha256(str(client_ip).encode()).hexdigest()[:16]
            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "path": scope.get("path"),
                "payment_header": payment_header.upper(),
                "status": status_code,
                "client_ref": client_ref,
            }
            print("capi2-payment-attempt: " + json.dumps(event, sort_keys=True, separators=(",", ":")), flush=True)


try:
    from x402.http.x402_http_server import x402HTTPResourceServer
except ModuleNotFoundError as exc:
    if exc.name and (exc.name == "x402" or exc.name.startswith("x402.")):
        print("x402-runtime-fix: deferred until x402 dependency is installed", flush=True)
    else:
        raise
else:
    current = x402HTTPResourceServer.process_settlement
    if getattr(current, "_capi2_settlement_logger", False):
        nonlocals = inspect.getclosurevars(current).nonlocals
        native = nonlocals.get("original")
        if not callable(native):
            raise RuntimeError("cannot recover native x402 process_settlement from capi2 wrapper")
        x402HTTPResourceServer.process_settlement = native
        current = native

    signature = inspect.signature(current)
    params = set(signature.parameters)
    required = {"self", "payment_payload", "requirements"}
    forbidden = {"before_handler_settlement", "phase"}
    if not required.issubset(params):
        raise RuntimeError(f"unexpected x402 process_settlement signature: {signature}")
    if forbidden & params:
        raise RuntimeError(f"incompatible x402 settlement signature remains: {signature}")

    print(f"x402-runtime-fix: native process_settlement active signature={signature}", flush=True)

    if _DEMAND_TOOLS_RUNTIME:
        try:
            from x402.server import x402ResourceServer

            original_register = x402ResourceServer.register
            if not getattr(original_register, "_capi2_safe_settlement_patch", False):
                @functools.wraps(original_register)
                def register_with_observer(self: Any, *args: Any, **kwargs: Any):
                    result = original_register(self, *args, **kwargs)
                    _install_demand_settlement_hooks(self)
                    return result

                register_with_observer._capi2_safe_settlement_patch = True
                x402ResourceServer.register = register_with_observer
        except Exception as exc:
            print(f"capi2-safe-settlement-observer: patch_error={type(exc).__name__}:{exc}", flush=True)

        try:
            from fastapi import FastAPI

            original_add_route = FastAPI.add_api_route
            if not getattr(original_add_route, "_capi2_conversion_patch", False):
                def add_api_route_patched(self: Any, path: str, endpoint: Any, *args: Any, **kwargs: Any):
                    if path == "/v1/x402/health":
                        kwargs["summary"] = _HEALTH_SUMMARY
                        kwargs["description"] = _HEALTH_DESCRIPTION

                    if path in {"/", "/.well-known/x402", "/v1/catalog"} and not getattr(endpoint, "_capi2_catalog_enriched", False):
                        if inspect.iscoroutinefunction(endpoint):
                            @functools.wraps(endpoint)
                            async def wrapped_endpoint(*ep_args: Any, __endpoint=endpoint, **ep_kwargs: Any):
                                return _enrich_catalog_payload(await __endpoint(*ep_args, **ep_kwargs))
                        else:
                            @functools.wraps(endpoint)
                            def wrapped_endpoint(*ep_args: Any, __endpoint=endpoint, **ep_kwargs: Any):
                                return _enrich_catalog_payload(__endpoint(*ep_args, **ep_kwargs))
                        wrapped_endpoint._capi2_catalog_enriched = True
                        endpoint = wrapped_endpoint

                    return original_add_route(self, path, endpoint, *args, **kwargs)

                add_api_route_patched._capi2_conversion_patch = True
                FastAPI.add_api_route = add_api_route_patched

            original_add_middleware = FastAPI.add_middleware
            if not getattr(original_add_middleware, "_capi2_payment_attempt_patch", False):
                def add_middleware_patched(self: Any, middleware_class: Any, *args: Any, **kwargs: Any):
                    routes = kwargs.get("routes") if getattr(middleware_class, "__name__", "") == "PaymentMiddlewareASGI" else None
                    paid_paths: list[str] = []
                    if isinstance(routes, dict):
                        for route_key, config in list(routes.items()):
                            parts = str(route_key).split(" ", 1)
                            if len(parts) == 2 and parts[0].upper() == "POST":
                                paid_paths.append(parts[1])
                            if str(route_key).endswith(" /v1/x402/health"):
                                try:
                                    config.description = _HEALTH_DESCRIPTION
                                except Exception:
                                    if hasattr(config, "model_copy"):
                                        routes[route_key] = config.model_copy(update={"description": _HEALTH_DESCRIPTION})

                    result = original_add_middleware(self, middleware_class, *args, **kwargs)
                    if paid_paths:
                        original_add_middleware(self, _PaymentAttemptObserverASGI, paid_paths=paid_paths)
                    return result

                add_middleware_patched._capi2_payment_attempt_patch = True
                FastAPI.add_middleware = add_middleware_patched
        except Exception as exc:
            print(f"capi2-conversion-runtime: patch_error={type(exc).__name__}:{exc}", flush=True)
