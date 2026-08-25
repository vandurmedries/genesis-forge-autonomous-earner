"""Non-invasive settlement observability for capi2 Claim Verify.

Uses the official x402 2.20.0 resource-server lifecycle hooks. It never wraps or
replaces process_settlement and therefore cannot change the native settlement
call signature or payment semantics.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=True)
    if isinstance(value, dict):
        return value
    out = {}
    for name in ("success", "error_reason", "error_message", "transaction", "network", "payer"):
        if hasattr(value, name):
            out[name] = getattr(value, name)
    return out


def _attempt_id(ctx: Any) -> str:
    try:
        payload = _plain(ctx.payment_payload)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()[:20]
    except Exception:
        return "unavailable"


def _result_fields(result: Any) -> dict[str, Any]:
    raw = _plain(result)
    return {
        "success": raw.get("success"),
        "errorReason": raw.get("errorReason", raw.get("error_reason")),
        "errorMessage": raw.get("errorMessage", raw.get("error_message")),
        "transaction": raw.get("transaction", ""),
        "network": raw.get("network"),
        "payer": raw.get("payer"),
    }


def install(server: Any, facilitator_url: str) -> None:
    """Attach read-only settlement hooks once."""
    if getattr(server, "_capi2_settlement_observer", False):
        return

    def after_settle(ctx: Any) -> None:
        try:
            event = {
                "event": "x402_settle_result",
                "attempt_id": _attempt_id(ctx),
                "facilitator": facilitator_url,
                **_result_fields(ctx.result),
            }
            print("capi2-settlement " + json.dumps(event, sort_keys=True, default=str), flush=True)
        except Exception as exc:
            print(
                f"capi2-settlement observer_error=after_settle:{type(exc).__name__}:{exc}",
                flush=True,
            )

    def settle_failure(ctx: Any) -> None:
        try:
            requirements = _plain(ctx.requirements)
            event = {
                "event": "x402_settle_failure",
                "attempt_id": _attempt_id(ctx),
                "facilitator": facilitator_url,
                "network": requirements.get("network"),
                "error_type": type(ctx.error).__name__,
                "error": str(ctx.error),
            }
            print("capi2-settlement " + json.dumps(event, sort_keys=True, default=str), flush=True)
        except Exception as exc:
            print(
                f"capi2-settlement observer_error=settle_failure:{type(exc).__name__}:{exc}",
                flush=True,
            )
        return None

    server.on_after_settle(after_settle)
    server.on_settle_failure(settle_failure)
    server._capi2_settlement_observer = True
    print(
        f"capi2-settlement-observer: installed facilitator={facilitator_url}",
        flush=True,
    )
