from __future__ import annotations

import json
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import psycopg
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, HttpUrl

app = FastAPI(
    title="capi2 Agent Marketplace Router",
    version="0.3.0",
    description=(
        "Machine-readable discovery, provider onboarding and routing for capi2 "
        "agent services and verified digital products."
    ),
)

STANDARD_FEE_BPS = 1000
PROVIDER_SHARE_BPS = 9000
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
REVENUE_WORKER_TOKEN = os.getenv("CAPI2_REVENUE_WORKER_TOKEN", "").strip()

ALLOWED_FINANCIAL_CLASSES = {
    "payments_fx_comparison",
    "loan_offer_analysis",
    "insurance_policy_analysis",
    "payment_fraud_wire_verification",
    "finance_vendor_comparison",
}

PROHIBITED_FINANCIAL_PHRASES = [
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

FIRST_PARTY_SERVICES: list[dict[str, Any]] = [
    {
        "service_id": "capi2.claim_verify.v1",
        "name": "capi2 Claim Verify",
        "provider_type": "first_party",
        "offer_type": "api_service",
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
            "amount": 0.01,
            "billing": "per_request",
        },
        "result": {"mode": "inline", "content_type": "application/json"},
    },
    {
        "service_id": "flippermit.pro.v1",
        "name": "FlipPermit Pro",
        "provider_type": "first_party",
        "offer_type": "digital_product",
        "status": "active",
        "capabilities": [
            "Etsy sourcing decision",
            "eBay to Etsy sourcing risk",
            "marketplace product eligibility",
            "dropshipping policy risk",
            "supplier fulfilment audit",
            "supplier delivery audit",
            "reseller unit economics",
            "maximum safe purchase price",
            "product decision passport",
            "reseller product validation",
            "GO HOLD STOP sourcing verdict",
        ],
        "regulated_financial_execution": False,
        "product_url": "https://flippermit.onrender.com/",
        "discovery_url": "https://flippermit.onrender.com/product.json",
        "quote_url": "https://flippermit.onrender.com/product.json",
        "execute": {
            "method": "GET",
            "url": "https://buy.stripe.com/5kQ14obVP0mlaTscWN5Vu0e",
        },
        "payment": {
            "protocol": "stripe_payment_link",
            "asset": "EUR",
            "network": "stripe",
            "price": "€9.90",
            "amount": 9.90,
            "billing": "one_time",
        },
        "result": {
            "mode": "redirect_after_payment",
            "content_type": "text/html",
            "delivery": "downloadable_offline_html",
        },
        "terms_url": "https://flippermit.onrender.com/terms.html",
        "privacy_url": "https://flippermit.onrender.com/privacy.html",
        "commercial_notes": [
            "single-business licence",
            "no subscription",
            "v1.x updates included",
            "decision support; no sales, profit or marketplace-approval guarantee",
        ],
    },
]

FINANCIAL_ROUTING_POLICY = {
    "capi2_role": "analysis_and_routing_only_for_regulated_financial_workflows",
    "allowed_non_execution_classes": sorted(ALLOWED_FINANCIAL_CLASSES),
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
    max_price_eur: Optional[float] = Field(default=None, ge=0)
    preferred_payment_protocol: Optional[str] = Field(default=None, max_length=50)
    regulated_financial_workflow: bool = False
    requested_action: Optional[str] = Field(default=None, max_length=200)


class ProviderRegistration(BaseModel):
    provider_name: str = Field(min_length=2, max_length=160)
    contact: Optional[str] = Field(default=None, max_length=320)
    capabilities: list[str] = Field(min_length=1, max_length=20)
    discovery_url: HttpUrl
    quote_url: HttpUrl
    execute_url: HttpUrl
    execute_method: Literal["GET", "POST"] = "POST"
    payment_protocol: str = Field(min_length=2, max_length=50)
    payment_asset: Optional[str] = Field(default=None, max_length=30)
    payment_network: Optional[str] = Field(default=None, max_length=100)
    price: str = Field(min_length=1, max_length=50)
    result_mode: Literal["inline", "poll"] = "inline"
    result_content_type: str = Field(default="application/json", max_length=100)
    financial_class: Optional[str] = Field(default=None, max_length=100)
    regulated_financial_execution: bool = False
    accepts_marketplace_fee_bps: int = Field(default=STANDARD_FEE_BPS)
    requested_provider_share_bps: int = Field(default=PROVIDER_SHARE_BPS)
    attest_no_custody_or_regulated_execution: bool = True


def _db_connect():
    if not DATABASE_URL:
        raise HTTPException(
            status_code=503,
            detail="provider_registry_database_not_configured",
        )
    return psycopg.connect(DATABASE_URL, connect_timeout=5)


def _init_db() -> None:
    if not DATABASE_URL:
        return
    with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_applications (
                    application_id TEXT PRIMARY KEY,
                    submitted_at TIMESTAMPTZ NOT NULL,
                    status TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    contact TEXT,
                    payload JSONB NOT NULL,
                    review_reason TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS capi2_revenue_runs (
                    run_id BIGSERIAL PRIMARY KEY,
                    started_at TIMESTAMPTZ NOT NULL,
                    completed_at TIMESTAMPTZ NOT NULL,
                    production TEXT NOT NULL,
                    discovery_resources INTEGER NOT NULL DEFAULT 0,
                    market_signals INTEGER NOT NULL DEFAULT 0,
                    verified_buyer_leads INTEGER NOT NULL DEFAULT 0,
                    actions_auto_approved INTEGER NOT NULL DEFAULT 0,
                    organic_revenue_cents BIGINT NOT NULL DEFAULT 0,
                    payload JSONB NOT NULL
                )
                """
            )
        conn.commit()


def _authorize_revenue_worker(authorization: str | None) -> None:
    if not REVENUE_WORKER_TOKEN:
        raise HTTPException(status_code=503, detail="revenue_worker_not_configured")
    supplied = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not secrets.compare_digest(supplied, REVENUE_WORKER_TOKEN):
        raise HTTPException(status_code=401, detail="invalid_worker_token")


@app.on_event("startup")
def startup() -> None:
    try:
        _init_db()
    except Exception as exc:
        print(
            "provider registry init deferred: "
            f"{exc.__class__.__name__}: {exc}"
        )


@app.post("/v1/internal/revenue-runs", include_in_schema=False)
def create_revenue_run(payload: dict[str, Any], authorization: str | None = Header(default=None)):
    _authorize_revenue_worker(authorization)
    if any(not payload.get(key) for key in ("startedAt", "completedAt", "production")):
        raise HTTPException(status_code=422, detail="invalid_revenue_run")
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO capi2_revenue_runs (
                    started_at, completed_at, production, discovery_resources,
                    market_signals, verified_buyer_leads, actions_auto_approved,
                    organic_revenue_cents, payload
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING run_id
                """,
                (
                    payload["startedAt"], payload["completedAt"], payload["production"],
                    int(payload.get("discoveryResources", 0)), int(payload.get("marketSignals", 0)),
                    int(payload.get("verifiedBuyerLeads", 0)), int(payload.get("actionsAutoApproved", 0)),
                    int(payload.get("organicRevenueCents", 0)), json.dumps(payload),
                ),
            )
            run_id = cur.fetchone()[0]
        conn.commit()
    return {"ok": True, "runId": run_id}


@app.get("/v1/revenue-runs/latest", include_in_schema=False)
def latest_revenue_run():
    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, started_at, completed_at, production,
                       discovery_resources, market_signals, verified_buyer_leads,
                       actions_auto_approved, organic_revenue_cents
                FROM capi2_revenue_runs ORDER BY run_id DESC LIMIT 1
                """
            )
            row = cur.fetchone()
    if not row:
        return {"lastRun": None}
    return {"lastRun": {
        "runId": row[0], "startedAt": row[1], "completedAt": row[2], "production": row[3],
        "discoveryResources": row[4], "marketSignals": row[5], "verifiedBuyerLeads": row[6],
        "actionsAutoApproved": row[7], "organicRevenueCents": row[8], "ok": True,
    }}


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
    searchable = " ".join(
        [service.get("name", ""), *service.get("capabilities", [])]
    )
    offered = _tokens(searchable)
    return len(wanted & offered) / max(1, len(wanted))


def _is_prohibited_financial_action(text: str) -> bool:
    normalized = text.lower()
    return any(phrase in normalized for phrase in PROHIBITED_FINANCIAL_PHRASES)


def _within_price_limit(service: dict[str, Any], request: RouteRequest) -> bool:
    payment = service.get("payment", {})
    amount = payment.get("amount")
    asset = str(payment.get("asset") or "").upper()
    if not isinstance(amount, (int, float)):
        return True
    if asset == "USDC" and request.max_price_usdc is not None:
        return amount <= request.max_price_usdc
    if asset == "EUR" and request.max_price_eur is not None:
        return amount <= request.max_price_eur
    return True


def _validate_provider_registration(registration: ProviderRegistration) -> None:
    if registration.accepts_marketplace_fee_bps != STANDARD_FEE_BPS:
        raise HTTPException(
            status_code=422,
            detail="capi2_standard_marketplace_fee_is_1000_bps",
        )
    if registration.requested_provider_share_bps != PROVIDER_SHARE_BPS:
        raise HTTPException(
            status_code=422,
            detail="capi2_standard_provider_share_is_9000_bps",
        )
    if registration.regulated_financial_execution:
        raise HTTPException(
            status_code=422,
            detail=(
                "regulated_financial_execution_agents_are_not_eligible_for_"
                "unlicensed_marketplace_routing"
            ),
        )
    if (
        registration.financial_class
        and registration.financial_class not in ALLOWED_FINANCIAL_CLASSES
    ):
        raise HTTPException(
            status_code=422,
            detail="financial_class_not_allowed_for_non_execution_provider",
        )
    combined = " ".join(registration.capabilities)
    if _is_prohibited_financial_action(combined):
        raise HTTPException(
            status_code=422,
            detail="provider_capability_contains_prohibited_regulated_execution",
        )
    if (
        registration.financial_class
        and not registration.attest_no_custody_or_regulated_execution
    ):
        raise HTTPException(
            status_code=422,
            detail="financial_provider_attestation_required",
        )


def _active_third_party_services() -> list[dict[str, Any]]:
    if not DATABASE_URL:
        return []
    try:
        with _db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT application_id, payload FROM provider_applications "
                    "WHERE status = 'active' ORDER BY submitted_at"
                )
                rows = cur.fetchall()
    except Exception:
        return []

    services: list[dict[str, Any]] = []
    for application_id, payload in rows:
        if isinstance(payload, str):
            payload = json.loads(payload)
        services.append(
            {
                "service_id": f"provider.{application_id}",
                "name": payload["provider_name"],
                "provider_type": "third_party",
                "offer_type": "api_service",
                "status": "active",
                "capabilities": payload["capabilities"],
                "financial_class": payload.get("financial_class"),
                "regulated_financial_execution": False,
                "discovery_url": payload["discovery_url"],
                "quote_url": payload["quote_url"],
                "execute": {
                    "method": payload["execute_method"],
                    "url": payload["execute_url"],
                },
                "payment": {
                    "protocol": payload["payment_protocol"],
                    "asset": payload.get("payment_asset"),
                    "network": payload.get("payment_network"),
                    "price": payload["price"],
                },
                "result": {
                    "mode": payload["result_mode"],
                    "content_type": payload["result_content_type"],
                },
                "marketplace_economics": {
                    "capi2_fee_bps": STANDARD_FEE_BPS,
                    "provider_share_bps": PROVIDER_SHARE_BPS,
                    "release_condition": (
                        "successful_delivery_and_required_payout_onboarding"
                    ),
                },
            }
        )
    return services


def _services() -> list[dict[str, Any]]:
    return FIRST_PARTY_SERVICES + _active_third_party_services()


@app.get("/health")
async def health() -> dict[str, Any]:
    services = _services()
    return {
        "ok": True,
        "service": "capi2-agent-marketplace-router",
        "version": "0.3.0",
        "active_services": len(services),
        "provider_registry_persistent": bool(DATABASE_URL),
        "standard_marketplace_fee_bps": STANDARD_FEE_BPS,
        "provider_share_bps": PROVIDER_SHARE_BPS,
    }


@app.get("/.well-known/agent.json")
async def agent_manifest() -> dict[str, Any]:
    return {
        "name": "capi2 Agent Marketplace Router",
        "protocol": "capi2.marketplace/0.3",
        "description": (
            "Discover verified capi2 services and digital products, request a "
            "machine-readable match, then follow the returned quote, payment, "
            "execution and delivery flow."
        ),
        "endpoints": {
            "catalog": {"method": "GET", "path": "/v1/services"},
            "route": {"method": "POST", "path": "/v1/route"},
            "policy": {"method": "GET", "path": "/v1/policy"},
            "provider_requirements": {
                "method": "GET",
                "path": "/v1/providers/requirements",
            },
            "provider_register": {
                "method": "POST",
                "path": "/v1/providers/register",
            },
            "provider_status": {
                "method": "GET",
                "path": "/v1/providers/{application_id}",
            },
        },
        "marketplace": {
            "standard_fee_bps": STANDARD_FEE_BPS,
            "provider_share_bps": PROVIDER_SHARE_BPS,
            "activation": (
                "Provider applications remain pending_verification until "
                "technical and compliance verification; registration alone "
                "never creates a sellable listing."
            ),
        },
        "supported_offer_types": ["api_service", "digital_product"],
        "supported_payment_protocols": ["x402", "stripe_payment_link"],
        "autonomous_flow": [
            "discover_marketplace",
            "request_capability_match",
            "fetch_offer_or_quote",
            "pay_via_returned_payment_protocol",
            "execute_service_or_follow_checkout",
            "receive_machine_readable_result_or_digital_delivery",
        ],
        "financial_routing_policy": FINANCIAL_ROUTING_POLICY,
    }


@app.get("/v1/services")
async def list_services() -> dict[str, Any]:
    services = _services()
    return {
        "protocol": "capi2.catalog/0.3",
        "services": services,
        "count": len(services),
    }


@app.get("/v1/policy")
async def policy() -> dict[str, Any]:
    return {
        "protocol": "capi2.policy/0.3",
        "marketplace": {
            "standard_fee_bps": STANDARD_FEE_BPS,
            "provider_share_bps": PROVIDER_SHARE_BPS,
            "disputes": (
                "private marketplace review under pre-agreed terms; no court "
                "or statutory arbitration representation"
            ),
            "digital_products": (
                "seller terms, payment-provider checkout and statutory rights "
                "apply; catalog inclusion is not a sales guarantee"
            ),
        },
        "financial_routing": FINANCIAL_ROUTING_POLICY,
    }


@app.get("/v1/providers/requirements")
async def provider_requirements() -> dict[str, Any]:
    return {
        "protocol": "capi2.provider_requirements/0.1",
        "economics": {
            "marketplace_fee_bps": STANDARD_FEE_BPS,
            "provider_share_bps": PROVIDER_SHARE_BPS,
        },
        "required": [
            "machine-readable discovery URL",
            "machine-readable quote URL",
            "public execute endpoint",
            "declared payment protocol and price",
            "machine-readable result",
        ],
        "activation": {
            "initial_status": "pending_verification",
            "sellable_only_when": (
                "status=active after technical and compliance verification"
            ),
        },
        "financial": FINANCIAL_ROUTING_POLICY,
    }


@app.post("/v1/providers/register")
async def register_provider(
    registration: ProviderRegistration,
) -> dict[str, Any]:
    _validate_provider_registration(registration)
    application_id = str(uuid.uuid4())
    submitted_at = datetime.now(timezone.utc)
    payload = registration.model_dump(mode="json")

    try:
        with _db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO provider_applications
                    (application_id, submitted_at, status, provider_name,
                     contact, payload, review_reason)
                    VALUES (%s, %s, 'pending_verification', %s, %s,
                            %s::jsonb, NULL)
                    """,
                    (
                        application_id,
                        submitted_at,
                        registration.provider_name,
                        registration.contact,
                        json.dumps(payload),
                    ),
                )
            conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "provider_registry_write_failed:"
                f"{exc.__class__.__name__}"
            ),
        ) from exc

    return {
        "protocol": "capi2.provider_registration/0.1",
        "application_id": application_id,
        "status": "pending_verification",
        "economics": {
            "marketplace_fee_bps": STANDARD_FEE_BPS,
            "provider_share_bps": PROVIDER_SHARE_BPS,
        },
        "message": (
            "Registration received. This is not marketplace activation. The "
            "service becomes sellable only after technical and compliance "
            "verification."
        ),
        "status_url": f"/v1/providers/{application_id}",
    }


@app.get("/v1/providers/{application_id}")
async def provider_status(application_id: str) -> dict[str, Any]:
    try:
        with _db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, provider_name, submitted_at, review_reason "
                    "FROM provider_applications WHERE application_id = %s",
                    (application_id,),
                )
                row = cur.fetchone()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "provider_registry_read_failed:"
                f"{exc.__class__.__name__}"
            ),
        ) from exc

    if not row:
        raise HTTPException(
            status_code=404,
            detail="provider_application_not_found",
        )
    status, provider_name, submitted_at, review_reason = row
    return {
        "protocol": "capi2.provider_status/0.1",
        "application_id": application_id,
        "provider_name": provider_name,
        "status": status,
        "submitted_at": submitted_at,
        "review_reason": review_reason,
        "sellable": status == "active",
    }


@app.post("/v1/route")
async def route(request: RouteRequest) -> dict[str, Any]:
    combined_action = (
        f"{request.capability} {request.requested_action or ''}".strip()
    )

    if (
        request.regulated_financial_workflow
        and _is_prohibited_financial_action(combined_action)
    ):
        return {
            "protocol": "capi2.route/0.3",
            "status": "licensed_provider_required",
            "reason": (
                "The requested action is a regulated execution, custody or "
                "advice step that capi2 and unlicensed provider agents do not "
                "perform."
            ),
            "next_step": (
                "Route to a licensed or otherwise authorized provider or its "
                "official onboarding flow."
            ),
            "financial_routing_policy": FINANCIAL_ROUTING_POLICY,
        }

    candidates: list[tuple[float, dict[str, Any]]] = []
    for service in _services():
        if service.get("status") != "active":
            continue
        if (
            request.preferred_payment_protocol
            and service.get("payment", {}).get("protocol")
            != request.preferred_payment_protocol
        ):
            continue
        if not _within_price_limit(service, request):
            continue
        score = _score_service(request.capability, service)
        if score > 0:
            candidates.append((score, service))

    candidates.sort(key=lambda item: item[0], reverse=True)
    if not candidates:
        return {
            "protocol": "capi2.route/0.3",
            "status": "no_active_match",
            "requested_capability": request.capability,
            "message": (
                "No currently active provider service or digital product "
                "matches this capability and price/payment constraint. Pending "
                "providers are not routed and no provider or approval is "
                "invented."
            ),
        }

    score, service = candidates[0]
    purchase_label = (
        "checkout"
        if service.get("offer_type") == "digital_product"
        else "pay_and_execute"
    )
    return {
        "protocol": "capi2.route/0.3",
        "status": "matched",
        "match_score": round(score, 3),
        "requested_capability": request.capability,
        "service": service,
        "next_actions": [
            {
                "step": "quote",
                "method": "GET",
                "url": service["quote_url"],
            },
            {"step": purchase_label, **service["execute"]},
            {"step": "result", **service["result"]},
        ],
    }
