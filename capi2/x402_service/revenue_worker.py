"""Machine-to-machine revenue-cycle trigger for the CAPI2 control plane."""
from __future__ import annotations

import os
import secrets
import threading
from datetime import datetime, timezone

import requests
from fastapi import Header, HTTPException


TOKEN = os.getenv("CAPI2_REVENUE_WORKER_TOKEN", "")
ORIGIN = os.getenv("CAPI2_CLAIM_VERIFY_ORIGIN", "https://capi2-claim-verify.onrender.com").rstrip("/")
REGISTRY_ORIGIN = os.getenv("CAPI2_REVENUE_REGISTRY_ORIGIN", "https://capi2-agent-marketplace-router.onrender.com").rstrip("/")
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _persist_run(payload: dict) -> int:
    response = requests.post(
        f"{REGISTRY_ORIGIN}/v1/internal/revenue-runs",
        json=payload,
        timeout=25,
        headers={"authorization": f"Bearer {TOKEN}", "user-agent": "capi2-revenue-worker/1.1"},
    )
    response.raise_for_status()
    return int(response.json()["runId"])


def _latest_run() -> dict | None:
    response = requests.get(f"{REGISTRY_ORIGIN}/v1/revenue-runs/latest", timeout=25)
    response.raise_for_status()
    value = response.json().get("lastRun")
    return value if isinstance(value, dict) else None


def install(app) -> None:
    @app.post("/v1/internal/revenue-cycle", include_in_schema=False)
    def revenue_cycle(authorization: str | None = Header(default=None)):
        _authorize(authorization)
        with _LOCK:
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
                    "startedAt": started_at,
                    "completedAt": _now(),
                    "production": "healthy" if health.get("ok") is True else health.get("status", "unknown"),
                    "discoveryResources": len(resources) if isinstance(resources, list) else 0,
                    "marketSignals": len(offers) if isinstance(offers, list) else 0,
                    "verifiedBuyerLeads": 0,
                    "actionsAutoApproved": 0,
                    "organicRevenueCents": 0,
                    "note": "Marketplace listings excluded from leads; no outbound executed without verified recipient.",
                }
                result["runId"] = _persist_run(result)
            except Exception as exc:
                result = {
                    "ok": False,
                    "startedAt": started_at,
                    "completedAt": _now(),
                    "error": "cycle_failed",
                    "reason": exc.__class__.__name__,
                }
            if not result["ok"]:
                raise HTTPException(status_code=502, detail=result)
            return result

    @app.get("/v1/revenue-worker/status", include_in_schema=False)
    def revenue_worker_status():
        try:
            state = _latest_run()
        except Exception:
            state = None
        return {
            "configured": bool(TOKEN),
            "lastRun": state or None,
            "trigger": "/v1/internal/revenue-cycle",
            "authentication": "Bearer token required",
        }
