"""Post-settlement revenue operations for capi2 demand tools.

This module never participates in payment verification or settlement. It only
observes successful x402 settlements and fan-outs a minimal, signed event to
configured back-office systems.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import urllib.request
from datetime import datetime, timezone
from typing import Any

def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, "model_dump"):
        return _plain(value.model_dump(mode="json"))
    if hasattr(value, "dict"):
        return _plain(value.dict())
    return str(value)


def _first(mapping: dict[str, Any], *keys: str) -> Any:
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


def settlement_event(ctx: Any, public_origin: str) -> dict[str, Any]:
    """Build a stable, non-secret event from an x402 after-settle context."""
    requirements = _plain(getattr(ctx, "requirements", None)) or {}
    payload = _plain(getattr(ctx, "payment_payload", None)) or {}
    result = _plain(getattr(ctx, "result", None)) or {}

    resource = _first(requirements, "resource", "url") or _first(payload, "resource", "url")
    payer = _deep_first(result, "payer", "from", "sender") or _deep_first(payload, "payer", "from", "sender")
    tx_hash = _first(result, "transaction", "transaction_hash", "tx_hash", "txHash")
    amount = _first(requirements, "amount", "max_amount_required", "maxAmountRequired", "price")
    network = _first(requirements, "network") or _first(payload, "network")

    if isinstance(resource, str) and resource.startswith(public_origin):
        path = resource[len(public_origin):] or "/"
    else:
        path = resource

    payer_ref = None
    if payer:
        payer_ref = "payer_" + hashlib.sha256(str(payer).lower().encode()).hexdigest()[:20]

    event_key = json.dumps({
        "transaction_hash": tx_hash,
        "resource": resource,
        "network": network,
        "payment_payload": payload if not tx_hash else None,
    }, sort_keys=True, separators=(",", ":"), default=str).encode()
    event = {
        "id": "capi2_settlement_" + hashlib.sha256(event_key).hexdigest()[:32],
        "type": "capi2.x402.settled",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "service": "capi2-demand-tools",
        "resource": resource,
        "path": path,
        "amount": amount,
        "asset": "USDC",
        "network": network,
        "payer_ref": payer_ref,
        "transaction_hash": tx_hash,
    }
    return {key: value for key, value in event.items() if value is not None}


def _targets() -> list[tuple[str, str]]:
    return [
        ("lago", os.getenv("CAPI2_LAGO_WEBHOOK_URL", "").strip()),
        ("trigger", os.getenv("CAPI2_TRIGGER_WEBHOOK_URL", "").strip()),
        ("crm", os.getenv("CAPI2_CRM_WEBHOOK_URL", "").strip()),
    ]


def _deliver(target: str, url: str, event: dict[str, Any]) -> None:
    body = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "capi2-revenue-ops/1.0",
        "Idempotency-Key": event["id"],
        "X-Capi2-Event": event["type"],
    }
    secret = os.getenv("CAPI2_REVENUE_WEBHOOK_SECRET", "")
    if secret:
        headers["X-Capi2-Signature"] = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=8) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"webhook_http_{response.status}")
    print(json.dumps({"event": "revenue_ops_delivered", "target": target, "event_id": event["id"]}), flush=True)


def dispatch(event: dict[str, Any]) -> None:
    """Deliver configured integrations out-of-band and fail open."""
    print("capi2-revenue " + json.dumps(event, sort_keys=True, default=str), flush=True)

    def worker() -> None:
        for target, url in _targets():
            if not url:
                continue
            try:
                _deliver(target, url, event)
            except Exception as exc:
                print(json.dumps({
                    "event": "revenue_ops_delivery_failed",
                    "target": target,
                    "event_id": event["id"],
                    "error": type(exc).__name__,
                }), flush=True)

    threading.Thread(target=worker, name="capi2-revenue-ops", daemon=True).start()


def install(server: Any, public_origin: str) -> None:
    """Attach exactly one observer to the native x402 success hook."""
    if getattr(server, "_capi2_revenue_ops", False):
        return

    def after_settle(ctx: Any) -> None:
        try:
            dispatch(settlement_event(ctx, public_origin))
        except Exception as exc:
            print(f"capi2-revenue observer_error={type(exc).__name__}", flush=True)

    server.on_after_settle(after_settle)
    server._capi2_revenue_ops = True
