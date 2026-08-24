from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(
    title="capi2 Agent Marketplace Router",
    version="0.1.0",
    description="Machine-readable discovery and routing layer for capi2 agent-to-agent services.",
)

STANDARD_FEE_BPS = 1000
PROVIDER_SHARE_BPS = 9000

SERVICES: list[dict[str, Any]] = [
    {
        "service_id": "capi2.claim_verify.v1",
        "name": "capi2 Claim Verify",
        "provider_type": "first_party",
        "status": "active",
        "capabilities": [
            "claim verification",
            "public evidence verification",
            "vendor claim evidence",
            "commercial readiness evidence",
            "public source verification",
        ],
        "regulated_financial_execution": False,
        "discovery_url": "https://capi2-claim-verify.onrender.com/.well-known/agent.json",
        "quote_url": "https://capi2-claim-verify.onrender.com/v1/quote",
        "execute": {
            "method": "POST",
            "url": "https://capi2-claim-verify.onrender.com/v1/claim-verify",
        },
        "payment": {
            "protocol": "x402",
            "asset": "USDC",
            "network": "eip155:8453",
            "price": "$0.01",
        },
        "result": {
            "mode": "inline",
            "content_type": "application/json",
        },
    }
]

FINANCIAL_ROUTING_POLICY = {
    "capi2_role": "analysis_and_routing_only_for_regulated_financial_workflows",
    "allowed_non_execution_classes": [
        "payments_fx_comparison",
        "loan_offer_analysis",
        "insurance_policy_analysis",
        "payment_fraud_wire_verification",
        "finance_vendor_comparison",
    ],
    "prohibited_for_capi2_or_unlicensed_agents": [
        "custody_funds",
        "execute_investments",
        "place_trades",
        "sell_insurance",
        "make_lending_decisions",
        "personalized_regulated_financial_advice",
    ],
    "regulated_steps": "licensed_or_authorized_provider_or_official_onboarding_flow_only",
}


class RouteRequest(BaseModel):
    capability: str = Field(min_length=2, max_length=500)
    max_price_usdc: Optional[float] = Field(default=None, ge=0)
    preferred_payment_protocol: Optional[str] = Field(default=None, max_length=50)
    regulated_financial_workflow: bool = False
    requested_action: Optional[str] = Field(default=None, max_length=200)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 3
    }


def _score_service(capability: str, service: dict[str, Any]) -> float:
    wanted = _tokens(capability)
    if not wanted:
        return 0.0
    haystack = " ".join(service.get("capabilities", []))
    offered = _tokens(haystack)
    return len(wanted & offered) / max(1, len(wanted))


def _is_prohibited_financial_action(text: str) -> bool:
    normalized = text.lower()
    phrases = [
        "custody",
        "hold funds",
        "execute trade",
        "place trade",
        "buy stock",
        "sell stock",
        "sell insurance",
        "underwrite",
        "approve loan",
        "deny loan",
        "lending decision",
        "personalized investment advice",
        "personal financial advice",
    ]
    return any(phrase in normalized for phrase in phrases)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "capi2-agent-marketplace-router",
        "version": "0.1.0",
        "active_services": len([s for s in SERVICES if s["status"] == "active"]),
        "standard_marketplace_fee_bps": STANDARD_FEE_BPS,
        "provider_share_bps": PROVIDER_SHARE_BPS,
    }


@app.get("/.well-known/agent.json")
async def agent_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Agent Marketplace Router",
        "protocol": "capi2.marketplace/0.1",
        "description": "Discover active capi2 services, request a machine-readable match, then follow the returned quote/payment/execute flow.",
        "endpoints": {
            "catalog": {"method": "GET", "path": "/v1/services"},
            "route": {"method": "POST", "path": "/v1/route"},
            "policy": {"method": "GET", "path": "/v1/policy"},
        },
        "marketplace": {
            "standard_fee_bps": STANDARD_FEE_BPS,
            "provider_share_bps": PROVIDER_SHARE_BPS,
            "settlement_note": "For routed third-party jobs, capi2 retains 10% and the provider receives 90% after successful delivery and required payout onboarding.",
        },
        "autonomous_flow": [
            "discover_marketplace",
            "request_capability_match",
            "fetch_provider_quote",
            "pay_via_returned_payment_protocol",
            "execute_provider_service",
            "receive_machine_readable_result",
        ],
        "financial_routing_policy": FINANCIAL_ROUTING_POLICY,
    }


@app.get("/v1/services")
async def list_services() -> dict[str, Any]:
    return {
        "protocol": "capi2.catalog/0.1",
        "services": [s for s in SERVICES if s["status"] == "active"],
        "count": len([s for s in SERVICES if s["status"] == "active"]),
    }


@app.get("/v1/policy")
async def policy() -> dict[str, Any]:
    return {
        "protocol": "capi2.policy/0.1",
        "marketplace": {
            "standard_fee_bps": STANDARD_FEE_BPS,
            "provider_share_bps": PROVIDER_SHARE_BPS,
            "disputes": "private marketplace review under pre-agreed terms; no court or statutory arbitration representation",
        },
        "financial_routing": FINANCIAL_ROUTING_POLICY,
    }


@app.post("/v1/route")
async def route(request: RouteRequest) -> dict[str, Any]:
    combined_action = f"{request.capability} {request.requested_action or ''}".strip()

    if request.regulated_financial_workflow and _is_prohibited_financial_action(combined_action):
        return {
            "protocol": "capi2.route/0.1",
            "status": "licensed_provider_required",
            "reason": "The requested action is a regulated execution/custody/advice step that capi2 and unlicensed provider agents do not perform.",
            "next_step": "Route to a licensed or otherwise authorized provider or its official onboarding flow.",
            "financial_routing_policy": FINANCIAL_ROUTING_POLICY,
        }

    candidates = []
    for service in SERVICES:
        if service.get("status") != "active":
            continue
        if request.preferred_payment_protocol:
            if service.get("payment", {}).get("protocol") != request.preferred_payment_protocol:
                continue
        score = _score_service(request.capability, service)
        if score > 0:
            candidates.append((score, service))

    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        return {
            "protocol": "capi2.route/0.1",
            "status": "no_active_match",
            "requested_capability": request.capability,
            "message": "No currently active provider service matches this capability. No provider or approval is being invented.",
        }

    score, service = candidates[0]
    return {
        "protocol": "capi2.route/0.1",
        "status": "matched",
        "match_score": round(score, 3),
        "requested_capability": request.capability,
        "service": service,
        "next_actions": [
            {"step": "quote", "method": "GET", "url": service["quote_url"]},
            {"step": "pay_and_execute", **service["execute"]},
            {"step": "result", **service["result"]},
        ],
    }
