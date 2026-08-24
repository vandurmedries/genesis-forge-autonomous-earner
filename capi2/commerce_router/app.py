from __future__ import annotations

import os
import re
import time
from typing import Any, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="capi2 Agent Commerce Router",
    version="0.1.0",
    description="Buyer-side discovery, quality-aware routing and broker pricing for agent-to-agent commerce.",
)

AGENT402_ORIGIN = os.getenv("CAPI2_AGENT402_ORIGIN", "https://agent402.tools").rstrip("/")
SELLER_ORIGIN = os.getenv("CAPI2_SELLER_ORIGIN", "https://capi2-claim-verify.onrender.com").rstrip("/")
EXTERNAL_BUYER_ENABLED = os.getenv("CAPI2_EXTERNAL_BUYER_ENABLED", "false").lower() == "true"
BROKER_DAILY_BUDGET_USD = float(os.getenv("CAPI2_BROKER_DAILY_BUDGET_USD", "0") or "0")
CACHE_TTL_SECONDS = int(os.getenv("CAPI2_COMMERCE_CACHE_TTL_SECONDS", "30"))

COMMERCE_TIERS = [
    {"tier": "base", "upstream_route": "/api/route/execute", "upstream_price_usd": 0.01, "underlying_max_usd": 0.005, "capi2_price_usd": 0.011, "broker_margin_usd": 0.001},
    {"tier": "plus", "upstream_route": "/api/route/execute-plus", "upstream_price_usd": 0.05, "underlying_max_usd": 0.04, "capi2_price_usd": 0.055, "broker_margin_usd": 0.005},
    {"tier": "max", "upstream_route": "/api/route/execute-max", "upstream_price_usd": 0.55, "underlying_max_usd": 0.50, "capi2_price_usd": 0.605, "broker_margin_usd": 0.055},
    {"tier": "pro", "upstream_route": "/api/route/execute-pro", "upstream_price_usd": 3.30, "underlying_max_usd": 3.00, "capi2_price_usd": 3.63, "broker_margin_usd": 0.33},
]

_registration_state: dict[str, Any] = {"attempted": False, "listed": False, "status_code": None, "detail": None, "checked_at": None}
_route_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class CommerceRouteRequest(BaseModel):
    task: str = Field(min_length=3, max_length=400)
    top: int = Field(default=5, ge=1, le=20)
    scope: Literal["all", "external"] = "all"
    max_buyer_price_usd: Optional[float] = Field(default=None, gt=0)


def _usd(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        n = float(value)
        return n if n >= 0 else None
    if isinstance(value, str):
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)", value.replace(",", ""))
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                return None
    return None


def _find_hint(node: Any) -> Optional[dict[str, Any]]:
    if isinstance(node, dict):
        hint = node.get("routeExecuteHint") or node.get("route_execute_hint")
        if isinstance(hint, dict):
            return hint
        if {"tool", "price"} <= set(node.keys()) and "route-execute" in str(node.get("tool", "")):
            return node
        for value in node.values():
            found = _find_hint(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_hint(item)
            if found:
                return found
    return None


def _collect_candidate_prices(node: Any, out: list[float]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"price", "priceUsd", "price_usd", "underlyingPriceUsd", "underlying_price_usd"}:
                n = _usd(value)
                if n is not None:
                    out.append(n)
            _collect_candidate_prices(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_candidate_prices(item, out)


def _tier_for_underlying(underlying_usd: float) -> Optional[dict[str, Any]]:
    for tier in COMMERCE_TIERS:
        if underlying_usd <= tier["underlying_max_usd"] + 1e-12:
            return tier
    return None


def _tier_from_upstream(data: dict[str, Any]) -> tuple[Optional[dict[str, Any]], Optional[float], str]:
    hint = _find_hint(data)
    if hint:
        underlying = _usd(hint.get("underlyingPriceUsd") or hint.get("underlying_price_usd"))
        tool = str(hint.get("tool", ""))
        for tier in COMMERCE_TIERS:
            suffix = tier["upstream_route"].rsplit("/", 1)[-1]
            if tool == suffix:
                return tier, underlying, "agent402_route_hint"
        hinted_price = _usd(hint.get("price"))
        if hinted_price is not None:
            for tier in COMMERCE_TIERS:
                if abs(tier["upstream_price_usd"] - hinted_price) < 1e-9:
                    return tier, underlying, "agent402_route_hint_price"

    prices: list[float] = []
    _collect_candidate_prices(data, prices)
    plausible = sorted(p for p in prices if 0 < p <= 3.0)
    if plausible:
        underlying = plausible[0]
        return _tier_for_underlying(underlying), underlying, "candidate_price_fallback"
    return None, None, "upstream_quote_shape_unknown"


async def _register_seller() -> None:
    global _registration_state
    now = time.time()
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.post(
                f"{AGENT402_ORIGIN}/api/index/register",
                json={"origin": SELLER_ORIGIN},
                headers={"user-agent": "capi2-commerce-router/0.1"},
            )
        try:
            detail: Any = response.json()
        except Exception:
            detail = response.text[:1000]
        _registration_state = {
            "attempted": True,
            "listed": bool(response.is_success and (not isinstance(detail, dict) or detail.get("listed", True))),
            "status_code": response.status_code,
            "detail": detail,
            "checked_at": int(now),
        }
        print(f"agent402 registration: status={response.status_code} listed={_registration_state['listed']}")
    except Exception as exc:
        _registration_state = {
            "attempted": True,
            "listed": False,
            "status_code": None,
            "detail": f"{exc.__class__.__name__}: {exc}",
            "checked_at": int(now),
        }
        print(f"agent402 registration deferred: {exc.__class__.__name__}: {exc}")


@app.on_event("startup")
async def startup() -> None:
    await _register_seller()


async def _agent402_route(request: CommerceRouteRequest) -> dict[str, Any]:
    cache_key = f"{request.scope}:{request.top}:{request.task.strip().lower()}"
    cached = _route_cache.get(cache_key)
    if cached and time.time() - cached[0] <= CACHE_TTL_SECONDS:
        return cached[1]

    payload: dict[str, Any] = {"query": request.task, "top": request.top}
    if request.scope == "external":
        payload["include"] = "external"

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.post(
                f"{AGENT402_ORIGIN}/api/route",
                json=payload,
                headers={"user-agent": "capi2-commerce-router/0.1"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"upstream_route_unreachable:{exc.__class__.__name__}") from exc

    if response.status_code >= 500:
        raise HTTPException(status_code=502, detail=f"upstream_route_status:{response.status_code}")
    if response.status_code >= 400:
        raise HTTPException(status_code=424, detail=f"upstream_route_rejected:{response.status_code}:{response.text[:300]}")

    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="upstream_route_returned_non_json") from exc

    _route_cache[cache_key] = (time.time(), data)
    return data


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "capi2-agent-commerce-router",
        "version": "0.1.0",
        "seller_origin": SELLER_ORIGIN,
        "upstream_router": AGENT402_ORIGIN,
        "seller_registration": _registration_state,
        "external_execution": {
            "enabled": EXTERNAL_BUYER_ENABLED,
            "daily_budget_usd": BROKER_DAILY_BUDGET_USD,
            "mode": "fail_closed_until_spending_wallet_and_budget_are_configured",
        },
    }


@app.get("/.well-known/agent.json")
async def manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Agent Commerce Router",
        "protocol": "capi2.commerce/0.1",
        "description": "Free buyer-side routing over proven x402 market liquidity with transparent capi2 broker pricing.",
        "flow": [
            "describe_task",
            "discover_and_rank_existing_paid_tools",
            "quote_capi2_broker_tier",
            "buyer_pays_capi2",
            "capi2_buys_selected_upstream_service",
            "relay_result_and_receipt",
        ],
        "endpoints": {
            "route": {"method": "POST", "path": "/v1/commerce/route", "paid": False},
            "tiers": {"method": "GET", "path": "/v1/commerce/tiers", "paid": False},
            "registration": {"method": "GET", "path": "/v1/commerce/registration", "paid": False},
            "status": {"method": "GET", "path": "/health", "paid": False},
        },
        "execution": {
            "status": "armed_but_fail_closed",
            "enabled": EXTERNAL_BUYER_ENABLED,
            "requires": ["dedicated_spending_wallet", "positive_budget", "paid_inbound_execution_route"],
        },
    }


@app.get("/v1/commerce/tiers")
async def tiers() -> dict[str, Any]:
    return {
        "protocol": "capi2.commerce_tiers/0.1",
        "pricing_rule": "10_percent_markup_over_the_selected_Agent402_route_execute_tier",
        "tiers": COMMERCE_TIERS,
    }


@app.get("/v1/commerce/registration")
async def registration() -> dict[str, Any]:
    return {
        "protocol": "capi2.commerce_registration/0.1",
        "seller_origin": SELLER_ORIGIN,
        "index": AGENT402_ORIGIN,
        **_registration_state,
    }


@app.post("/v1/commerce/route")
async def commerce_route(request: CommerceRouteRequest) -> dict[str, Any]:
    upstream = await _agent402_route(request)
    tier, underlying_usd, source = _tier_from_upstream(upstream)

    if tier is None:
        return {
            "protocol": "capi2.commerce_route/0.1",
            "status": "match_found_but_no_safe_broker_tier",
            "task": request.task,
            "tier_resolution": source,
            "upstream": upstream,
            "execution_enabled": False,
        }

    if request.max_buyer_price_usd is not None and tier["capi2_price_usd"] > request.max_buyer_price_usd:
        return {
            "protocol": "capi2.commerce_route/0.1",
            "status": "buyer_price_cap_exceeded",
            "task": request.task,
            "max_buyer_price_usd": request.max_buyer_price_usd,
            "required_buyer_price_usd": tier["capi2_price_usd"],
            "selected_tier": tier,
        }

    return {
        "protocol": "capi2.commerce_route/0.1",
        "status": "quoted",
        "task": request.task,
        "scope": request.scope,
        "selected_tier": tier,
        "underlying_tool_price_usd": underlying_usd,
        "tier_resolution": source,
        "buyer_quote": {
            "price_usd": tier["capi2_price_usd"],
            "payment_protocol": "x402",
            "asset": "USDC",
            "network_preference": "eip155:8453",
        },
        "broker_economics": {
            "upstream_route_cost_usd": tier["upstream_price_usd"],
            "capi2_margin_usd": tier["broker_margin_usd"],
            "markup_bps": 1000,
        },
        "execution": {
            "enabled": EXTERNAL_BUYER_ENABLED and BROKER_DAILY_BUDGET_USD > 0,
            "status": (
                "ready_for_paid_execution_surface"
                if EXTERNAL_BUYER_ENABLED and BROKER_DAILY_BUDGET_USD > 0
                else "fail_closed_pending_spending_wallet_and_positive_budget"
            ),
        },
        "upstream": upstream,
    }
