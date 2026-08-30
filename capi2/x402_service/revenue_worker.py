"""Machine-to-machine revenue-cycle trigger for the CAPI2 control plane."""
from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import Header, HTTPException


STATE_PATH = Path(os.getenv("CAPI2_REVENUE_STATE_PATH", "/tmp/capi2-revenue-worker.json"))
TOKEN = os.getenv("CAPI2_REVENUE_WORKER_TOKEN", "")
ORIGIN = os.getenv("CAPI2_CLAIM_VERIFY_ORIGIN", "https://capi2-claim-verify.onrender.com").rstrip("/")
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_state() -> dict:
    try:
        value = json.loads(STATE_PATH.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(value: dict) -> None:
    STATE_PATH.write_text(json.dumps(value, sort_keys=True))


def _authorize(authorization: str | None) -> None:
    if not TOKEN:
        raise HTTPException(status_code=503, detail="revenue_worker_not_configured")
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not secrets.compare_digest(supplied, TOKEN):
        raise HTTPException(status_code=401, detail="invalid_worker_token")


def _get_json(path: str) -> dict:
    response = requests.get(f"{ORIGIN}{path}", timeout=25, headers={"user-agent": "capi2-revenue-worker/1.0"})
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def install(app) -> None:
    @app.post("/v1/internal/revenue-cycle", include_in_schema=False)
    def revenue_cycle(authorization: str | None = Header(default=None)):
        _authorize(authorization)
        with _LOCK:
            prior = _read_state()
            run_id = int(prior.get("run_id", 0)) + 1
            started_at = _now()
            try:
                health = _get_json("/health")
                discovery = _get_json("/.well-known/x402")
                radar = _get_json("/v1/free-x402-market-radar?q=agent%20verification&limit=5")
                resources = discovery.get("resources") or discovery.get("services") or []
                offers = radar.get("offers") or []
                # Public marketplace offers are market information, never buyer leads.
                result = {
                    "ok": True,
                    "runId": run_id,
                    "startedAt": started_at,
                    "completedAt": _now(),
                    "production": "healthy" if health.get("ok") is True else health.get("status", "unknown"),
                    "discoveryResources": len(resources) if isinstance(resources, list) else 0,
                    "marketSignals": len(offers) if isinstance(offers, list) else 0,
                    "verifiedBuyerLeads": 0,
                    "actionsAutoApproved": 0,
                    "organicRevenueCents": int(prior.get("organicRevenueCents", 0)),
                    "note": "Marketplace listings excluded from leads; no outbound executed without verified recipient.",
                }
            except Exception as exc:
                result = {
                    "ok": False,
                    "runId": run_id,
                    "startedAt": started_at,
                    "completedAt": _now(),
                    "error": "cycle_failed",
                    "reason": exc.__class__.__name__,
                }
            _write_state(result)
            if not result["ok"]:
                raise HTTPException(status_code=502, detail=result)
            return result

    @app.get("/v1/revenue-worker/status", include_in_schema=False)
    def revenue_worker_status():
        state = _read_state()
        return {
            "configured": bool(TOKEN),
            "lastRun": state or None,
            "trigger": "/v1/internal/revenue-cycle",
            "authentication": "Bearer token required",
        }
