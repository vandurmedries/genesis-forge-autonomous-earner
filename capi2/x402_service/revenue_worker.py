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

PRODUCT_LADDER = [
    {"id": "free_preview", "priceUsd": 0, "path": "/v1/sales/preflight"},
    {"id": "risk_report", "priceUsd": 29, "path": "/v1/reports/commerce-assurance"},
    {"id": "endpoint_check", "priceUsd": 49, "path": "/v1/products/endpoint-check"},
    {"id": "launch_pack", "priceUsd": 149, "path": "/v1/products/launch-pack"},
    {"id": "verification_integration", "priceUsd": 199, "path": "/v1/products/verification-integration"},
]


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


def _sales_decision(discovery_resources: int, market_signals: int, verified_leads: int, revenue_cents: int) -> dict:
    """Choose exactly one highest-value sales objective for this cycle."""
    if discovery_resources < 1:
        return {"stage": "distribution", "objective": "restore_machine_discovery", "product": "risk_report", "autoExecutable": True}
    if verified_leads < 1:
        return {"stage": "acquisition", "objective": "attract_verified_preview_users", "product": "free_preview", "autoExecutable": True, "cta": f"{ORIGIN}/buy"}
    if revenue_cents < 2900:
        return {"stage": "conversion", "objective": "convert_verified_preview_to_paid_report", "product": "risk_report", "autoExecutable": False, "requires": "verified recipient or inbound session"}
    return {"stage": "expansion", "objective": "upsell_existing_buyer", "product": "endpoint_check", "autoExecutable": False, "requires": "confirmed buyer relationship"}


def install(app) -> None:
    def _execute_cycle() -> dict:
        started_at = _now()
        health = _get_json("/health")
        discovery = _get_json("/.well-known/x402")
        radar = _get_json("/v1/free-x402-market-radar?q=agent%20verification&limit=5")
        resources = discovery.get("resources") or discovery.get("services") or []
        offers = radar.get("offers") or []
        discovery_count = len(resources) if isinstance(resources, list) else 0
        signal_count = len(offers) if isinstance(offers, list) else 0
        verified_leads = 0
        organic_revenue_cents = 0
        decision = _sales_decision(discovery_count, signal_count, verified_leads, organic_revenue_cents)
        result = {
            "ok": True,
            "startedAt": started_at,
            "completedAt": _now(),
            "production": "healthy" if health.get("ok") is True else health.get("status", "unknown"),
            "discoveryResources": discovery_count,
            "marketSignals": signal_count,
            "verifiedBuyerLeads": verified_leads,
            "actionsAutoApproved": 1 if decision.get("autoExecutable") else 0,
            "organicRevenueCents": organic_revenue_cents,
            "salesBot": decision,
            "note": "Sales Bot selected one conversion objective. Marketplace listings remain market information, never buyer leads.",
        }
        result["runId"] = _persist_run(result)
        return result

    @app.post("/v1/internal/revenue-cycle", include_in_schema=False)
    def revenue_cycle(authorization: str | None = Header(default=None)):
        _authorize(authorization)
        with _LOCK:
            try:
                result = _execute_cycle()
            except Exception as exc:
                result = {
                    "ok": False,
                    "startedAt": _now(),
                    "completedAt": _now(),
                    "error": "cycle_failed",
                    "reason": exc.__class__.__name__,
                }
            if not result["ok"]:
                raise HTTPException(status_code=502, detail=result)
            return result

    @app.post("/v1/internal/sales-bot/cycle", include_in_schema=False)
    def sales_bot_cycle(authorization: str | None = Header(default=None)):
        _authorize(authorization)
        with _LOCK:
            try:
                return _execute_cycle()
            except Exception as exc:
                raise HTTPException(status_code=502, detail={"ok": False, "error": "sales_cycle_failed", "reason": exc.__class__.__name__})

    @app.get("/v1/sales-bot")
    def sales_bot_manifest():
        return {
            "name": "CAPI2 Sales Bot",
            "mission": "sell, measure, learn, repeat",
            "cadence": "every 15 minutes",
            "singleCycleRule": "select exactly one highest-value sales objective",
            "productLadder": PRODUCT_LADDER,
            "funnel": ["machine discovery", "free preview", "$29 report", "$49 check", "$149 launch", "$199 integration", "retention"],
            "successMetric": "confirmed organic revenue from external buyers",
            "guardrails": ["no spam", "no invented leads", "no guaranteed-income claims", "no external message without a verified recipient", "tests and owner-funded payments excluded from revenue"],
            "status": "/v1/revenue-worker/status",
        }

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
