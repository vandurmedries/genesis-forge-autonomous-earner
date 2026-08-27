from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import httpx
from eth_account import Account
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from x402 import max_amount, prefer_network, x402Client
from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption, x402HTTPClient
from x402.http.clients import x402HttpxClient
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.mechanisms.evm.exact.register import register_exact_evm_client
from x402.server import x402ResourceServer

AGENT402_ORIGIN = os.getenv("CAPI2_AGENT402_ORIGIN", "https://agent402.tools").rstrip("/")
PUBLIC_ORIGIN = os.getenv(
    "CAPI2_WHOLESALE_ORIGIN", "https://capi2-wholesale-router.onrender.com"
).rstrip("/")
NETWORK = os.getenv("CAPI2_WHOLESALE_NETWORK", "eip155:8453")
FACILITATOR_URL = os.getenv(
    "CAPI2_WHOLESALE_FACILITATOR", "https://facilitator.xpay.sh"
).rstrip("/")
PRIVATE_KEY = os.getenv("CAPI2_WHOLESALE_EVM_PRIVATE_KEY", "").strip()
FALLBACK_PAY_TO = os.getenv("CAPI2_WHOLESALE_PAY_TO", "").strip()
UPSTREAM_TIMEOUT_SECONDS = float(os.getenv("CAPI2_WHOLESALE_UPSTREAM_TIMEOUT_SECONDS", "90"))

if PRIVATE_KEY:
    _wallet_account = Account.from_key(PRIVATE_KEY)
    PAY_TO = _wallet_account.address
else:
    _wallet_account = None
    PAY_TO = FALLBACK_PAY_TO

if not PAY_TO:
    raise RuntimeError(
        "Set CAPI2_WHOLESALE_EVM_PRIVATE_KEY or CAPI2_WHOLESALE_PAY_TO before starting."
    )

TIERS: dict[str, dict[str, Any]] = {
    "base": {
        "path": "/v1/wholesale/execute",
        "upstream_path": "/api/route/execute",
        "sale_price": "$0.011",
        "sale_price_usd": 0.011,
        "upstream_price_usd": 0.010,
        "underlying_max_usd": 0.005,
    },
    "plus": {
        "path": "/v1/wholesale/execute-plus",
        "upstream_path": "/api/route/execute-plus",
        "sale_price": "$0.055",
        "sale_price_usd": 0.055,
        "upstream_price_usd": 0.050,
        "underlying_max_usd": 0.040,
    },
    "max": {
        "path": "/v1/wholesale/execute-max",
        "upstream_path": "/api/route/execute-max",
        "sale_price": "$0.605",
        "sale_price_usd": 0.605,
        "upstream_price_usd": 0.550,
        "underlying_max_usd": 0.500,
    },
}

for tier in TIERS.values():
    tier["gross_margin_usd"] = round(
        tier["sale_price_usd"] - tier["upstream_price_usd"], 6
    )
    tier["gross_margin_pct"] = round(
        100 * tier["gross_margin_usd"] / tier["sale_price_usd"], 2
    )

app = FastAPI(
    title="capi2 Wholesale Agent Router",
    version="1.0.0",
    description=(
        "Zero-inventory agent-service resale: the buyer pays capi2 first, "
        "then capi2 purchases a routed upstream x402 service and relays the result."
    ),
)

facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
resource_server = x402ResourceServer(facilitator)
resource_server.register(NETWORK, ExactEvmServerScheme())


def _route_config(tier_name: str, tier: dict[str, Any]) -> RouteConfig:
    return RouteConfig(
        accepts=[
            PaymentOption(
                scheme="exact",
                pay_to=PAY_TO,
                price=tier["sale_price"],
                network=NETWORK,
            )
        ],
        resource=f"{PUBLIC_ORIGIN}{tier['path']}",
        mime_type="application/json",
        description=(
            f"capi2 wholesale {tier_name} route: pay capi2, then capi2 buys and relays "
            f"an Agent402-routed service. Gross broker margin {tier['gross_margin_usd']:.3f} USD."
        ),
        service_name=f"capi2 Wholesale Router {tier_name.title()}",
        tags=["agent commerce", "x402", "wholesale", "broker", "dropshipping"],
    )


protected_routes = {
    f"POST {tier['path']}": _route_config(name, tier)
    for name, tier in TIERS.items()
}
app.add_middleware(
    PaymentMiddlewareASGI,
    routes=protected_routes,
    server=resource_server,
)


class WholesaleRequest(BaseModel):
    task: str = Field(min_length=3, max_length=500)
    params: dict[str, Any] = Field(default_factory=dict)
    include: Literal["external", "all"] = "external"


class QuoteRequest(BaseModel):
    task: str = Field(min_length=3, max_length=500)
    include: Literal["external", "all"] = "external"
    top: int = Field(default=5, ge=1, le=20)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _usd(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        n = float(value)
        return n if n >= 0 else None
    if isinstance(value, str):
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)", value.replace(",", ""))
        if match:
            try:
                return float(match.group(1))
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


def _collect_prices(node: Any, out: list[float]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {
                "price",
                "priceUsd",
                "price_usd",
                "underlyingPriceUsd",
                "underlying_price_usd",
            }:
                parsed = _usd(value)
                if parsed is not None:
                    out.append(parsed)
            _collect_prices(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect_prices(item, out)


def _tier_for_underlying(price_usd: float) -> Optional[str]:
    for tier_name in ("base", "plus", "max"):
        if price_usd <= TIERS[tier_name]["underlying_max_usd"] + 1e-12:
            return tier_name
    return None


def _resolve_tier(upstream: dict[str, Any]) -> tuple[Optional[str], Optional[float], str]:
    hint = _find_hint(upstream)
    if hint:
        tool = str(hint.get("tool", ""))
        underlying = _usd(
            hint.get("underlyingPriceUsd") or hint.get("underlying_price_usd")
        )
        for tier_name, tier in TIERS.items():
            if tool == tier["upstream_path"].rsplit("/", 1)[-1]:
                return tier_name, underlying, "agent402_route_hint"
        hinted_price = _usd(hint.get("price"))
        if hinted_price is not None:
            for tier_name, tier in TIERS.items():
                if abs(tier["upstream_price_usd"] - hinted_price) < 1e-9:
                    return tier_name, underlying, "agent402_route_hint_price"

    prices: list[float] = []
    _collect_prices(upstream, prices)
    plausible = sorted(p for p in prices if 0 < p <= 0.5)
    if plausible:
        underlying = plausible[0]
        return _tier_for_underlying(underlying), underlying, "candidate_price_fallback"
    return None, None, "upstream_quote_shape_unknown"


async def _free_agent402_quote(request: QuoteRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": request.task, "top": request.top}
    if request.include == "external":
        payload["include"] = "external"
    try:
        async with httpx.AsyncClient(
            timeout=20.0, follow_redirects=True
        ) as client:
            response = await client.post(
                f"{AGENT402_ORIGIN}/api/route",
                json=payload,
                headers={"user-agent": "capi2-wholesale-router/1.0"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"upstream_quote_unreachable:{exc.__class__.__name__}",
        ) from exc

    if response.status_code >= 500:
        raise HTTPException(
            status_code=502, detail=f"upstream_quote_status:{response.status_code}"
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=424,
            detail=f"upstream_quote_rejected:{response.status_code}:{response.text[:300]}",
        )
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502, detail="upstream_quote_returned_non_json"
        ) from exc


def _payment_client(max_upstream_usd: float) -> tuple[x402Client, x402HTTPClient]:
    if _wallet_account is None:
        raise HTTPException(
            status_code=503,
            detail="wholesale_spending_wallet_not_configured",
        )
    client = x402Client()
    register_exact_evm_client(
        client,
        EthAccountSigner(_wallet_account),
        networks=NETWORK,
        policies=[
            max_amount(int(round(max_upstream_usd * 1_000_000))),
            prefer_network(NETWORK),
        ],
    )
    return client, x402HTTPClient(client)


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


async def _execute_upstream(
    tier_name: str, request: WholesaleRequest
) -> dict[str, Any]:
    tier = TIERS[tier_name]
    x402_client, http_client = _payment_client(tier["upstream_price_usd"])
    payload: dict[str, Any] = {
        "task": request.task,
        "params": request.params,
    }
    if request.include == "external":
        payload["include"] = "external"

    started = time.monotonic()
    try:
        async with x402HttpxClient(
            x402_client,
            timeout=UPSTREAM_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"user-agent": "capi2-wholesale-router/1.0"},
        ) as client:
            response = await client.post(
                f"{AGENT402_ORIGIN}{tier['upstream_path']}",
                json=payload,
            )
            await response.aread()
    except Exception as exc:
        print(
            "capi2-wholesale-upstream: "
            + json.dumps(
                {
                    "success": False,
                    "tier": tier_name,
                    "error": exc.__class__.__name__,
                    "occurred_at": _utc_now(),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        raise HTTPException(
            status_code=502,
            detail=f"upstream_paid_execution_failed:{exc.__class__.__name__}",
        ) from exc

    latency_ms = int((time.monotonic() - started) * 1000)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"upstream_paid_execution_status:{response.status_code}:{response.text[:300]}",
        )

    try:
        body: Any = response.json()
    except ValueError:
        body = {"text": response.text}

    settle = http_client.get_payment_settle_response(
        lambda name: response.headers.get(name)
    )
    settle_plain = _plain(settle)
    print(
        "capi2-wholesale-upstream: "
        + json.dumps(
            {
                "success": True,
                "tier": tier_name,
                "upstream_price_usd": tier["upstream_price_usd"],
                "latency_ms": latency_ms,
                "settlement": settle_plain,
                "occurred_at": _utc_now(),
            },
            sort_keys=True,
            default=str,
        ),
        flush=True,
    )
    return {
        "upstream_result": body,
        "upstream_settlement": settle_plain,
        "latency_ms": latency_ms,
    }


def _log_inbound_settlement(ctx: Any) -> None:
    try:
        requirements = _plain(getattr(ctx, "requirements", None)) or {}
        result = _plain(getattr(ctx, "result", None)) or {}
        payload = _plain(getattr(ctx, "payment_payload", None)) or {}
        resource = requirements.get("resource") or payload.get("resource")
        transaction = (
            result.get("transaction")
            or result.get("transaction_hash")
            or result.get("txHash")
        )
        event = {
            "success": bool(result.get("success", True)),
            "resource": resource,
            "amount": requirements.get("amount")
            or requirements.get("price")
            or requirements.get("maxAmountRequired"),
            "network": requirements.get("network") or payload.get("network"),
            "transaction": transaction,
            "occurred_at": _utc_now(),
        }
        print(
            "capi2-wholesale-settlement: "
            + json.dumps(event, sort_keys=True, default=str),
            flush=True,
        )
    except Exception as exc:
        print(
            f"capi2-wholesale-settlement: observer_error={exc.__class__.__name__}",
            flush=True,
        )


resource_server.on_after_settle(_log_inbound_settlement)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "name": "capi2 Wholesale Agent Router",
        "protocol": "capi2.wholesale/1.0",
        "model": "zero_inventory_digital_service_resale",
        "flow": [
            "free_quote",
            "buyer_pays_capi2_via_x402",
            "inbound_payment_settles",
            "capi2_pays_agent402_route",
            "agent402_selects_and_pays_supplier",
            "capi2_relays_result_and_receipts",
        ],
        "quote": f"{PUBLIC_ORIGIN}/v1/wholesale/quote",
        "tiers": TIERS,
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "capi2-wholesale-router",
        "version": "1.0.0",
        "origin": PUBLIC_ORIGIN,
        "network": NETWORK,
        "asset": "USDC",
        "pay_to": PAY_TO,
        "spending_wallet_configured": _wallet_account is not None,
        "supplier_router": AGENT402_ORIGIN,
        "mode": "buyer_funds_before_supplier_spend",
        "tiers": TIERS,
    }


@app.get("/.well-known/agent.json")
async def agent_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Wholesale Agent Router",
        "protocol": "capi2.wholesale/1.0",
        "description": (
            "One capi2 interface that quotes, buys and relays external x402 agent services. "
            "No inventory is purchased before the buyer's x402 payment settles."
        ),
        "payment": {
            "protocol": "x402",
            "network": NETWORK,
            "asset": "USDC",
            "payTo": PAY_TO,
        },
        "endpoints": {
            "quote": {
                "method": "POST",
                "path": "/v1/wholesale/quote",
                "paid": False,
            },
            **{
                tier_name: {
                    "method": "POST",
                    "path": tier["path"],
                    "paid": True,
                    "price": tier["sale_price"],
                }
                for tier_name, tier in TIERS.items()
            },
        },
        "economics": TIERS,
    }


@app.get("/.well-known/x402")
async def x402_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Wholesale Agent Router",
        "protocol": "x402",
        "network": NETWORK,
        "asset": "USDC",
        "payTo": PAY_TO,
        "resources": [
            {
                "resource": f"{PUBLIC_ORIGIN}{tier['path']}",
                "method": "POST",
                "price": tier["sale_price"],
                "service_name": f"capi2 Wholesale Router {name.title()}",
                "description": (
                    f"Pay capi2 {tier['sale_price']} and receive a routed upstream agent result."
                ),
                "tags": [
                    "agent commerce",
                    "dropshipping",
                    "wholesale",
                    "broker",
                    "x402",
                ],
            }
            for name, tier in TIERS.items()
        ],
    }


@app.post("/v1/wholesale/quote")
async def quote(request: QuoteRequest) -> dict[str, Any]:
    upstream = await _free_agent402_quote(request)
    tier_name, underlying_usd, resolution = _resolve_tier(upstream)
    if tier_name is None:
        return {
            "protocol": "capi2.wholesale_quote/1.0",
            "status": "no_safe_tier",
            "task": request.task,
            "tier_resolution": resolution,
            "upstream": upstream,
        }
    tier = TIERS[tier_name]
    return {
        "protocol": "capi2.wholesale_quote/1.0",
        "status": "quoted",
        "task": request.task,
        "include": request.include,
        "selected_tier": tier_name,
        "underlying_tool_price_usd": underlying_usd,
        "buyer_price_usd": tier["sale_price_usd"],
        "execute": {
            "method": "POST",
            "url": f"{PUBLIC_ORIGIN}{tier['path']}",
            "price": tier["sale_price"],
            "network": NETWORK,
            "asset": "USDC",
        },
        "broker_economics": {
            "upstream_router_cost_usd": tier["upstream_price_usd"],
            "gross_margin_usd": tier["gross_margin_usd"],
            "gross_margin_pct": tier["gross_margin_pct"],
        },
        "tier_resolution": resolution,
        "upstream": upstream,
    }


async def _paid_execute(
    tier_name: str, request: WholesaleRequest
) -> dict[str, Any]:
    tier = TIERS[tier_name]
    fulfillment = await _execute_upstream(tier_name, request)
    return {
        "protocol": "capi2.wholesale_result/1.0",
        "status": "fulfilled",
        "task": request.task,
        "supplier_scope": request.include,
        "tier": tier_name,
        "buyer_paid_usd": tier["sale_price_usd"],
        "upstream_router_cost_usd": tier["upstream_price_usd"],
        "gross_margin_usd": tier["gross_margin_usd"],
        "result": fulfillment["upstream_result"],
        "receipts": {
            "upstream_x402": fulfillment["upstream_settlement"],
        },
        "latency_ms": fulfillment["latency_ms"],
    }


@app.post("/v1/wholesale/execute")
async def execute_base(request: WholesaleRequest) -> dict[str, Any]:
    return await _paid_execute("base", request)


@app.post("/v1/wholesale/execute-plus")
async def execute_plus(request: WholesaleRequest) -> dict[str, Any]:
    return await _paid_execute("plus", request)


@app.post("/v1/wholesale/execute-max")
async def execute_max(request: WholesaleRequest) -> dict[str, Any]:
    return await _paid_execute("max", request)
