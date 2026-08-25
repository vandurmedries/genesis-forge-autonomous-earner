"""High-intent x402 sales surface for capi2 Claim Verify.

Keeps the canonical /v1/claim-verify route intact while exposing intent-specific
paid aliases that autonomous buyers can discover by job-to-be-done.
"""
from __future__ import annotations

try:  # Package import in CI/tests.
    from .app import (
        app,
        server,
        PAY_TO,
        PRICE,
        NETWORK,
        PUBLIC_ORIGIN,
        SERVICE_VERSION,
        CLAIM_INPUT_SCHEMA,
        CLAIM_OUTPUT_EXAMPLE,
        ClaimVerifyRequest,
        ClaimVerifyResponse,
        _execute_claim_verify,
    )
except ImportError:  # Render rootDir starts uvicorn from this directory.
    from app import (
        app,
        server,
        PAY_TO,
        PRICE,
        NETWORK,
        PUBLIC_ORIGIN,
        SERVICE_VERSION,
        CLAIM_INPUT_SCHEMA,
        CLAIM_OUTPUT_EXAMPLE,
        ClaimVerifyRequest,
        ClaimVerifyResponse,
        _execute_claim_verify,
    )

from x402.http import PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig


SALES_INTENTS = {
    "/v1/vendor-security-check": {
        "service_name": "capi2 Vendor Security Claim Check",
        "summary": "Verify a vendor security or compliance claim against public evidence.",
        "tags": ["security", "vendor risk", "SOC 2", "compliance", "due diligence"],
        "buyer_queries": [
            "verify vendor security claim",
            "check SOC 2 or encryption claim",
            "vendor security due diligence",
            "security questionnaire evidence check",
        ],
        "request_type": "vendor_security",
    },
    "/v1/procurement-claim-check": {
        "service_name": "capi2 Procurement Claim Check",
        "summary": "Verify a SaaS, procurement, RFP or commercial vendor claim.",
        "tags": ["procurement", "SaaS", "RFP", "vendor due diligence", "commercial"],
        "buyer_queries": [
            "verify SaaS vendor claim",
            "procurement evidence check",
            "RFP vendor claim verification",
            "commercial due diligence",
        ],
        "request_type": "procurement",
    },
    "/v1/data-clause-check": {
        "service_name": "capi2 AI Data Clause Claim Check",
        "summary": "Verify an AI/data/privacy vendor claim against a public policy or contract source.",
        "tags": ["AI data", "privacy", "DPA", "GDPR", "contract review"],
        "buyer_queries": [
            "verify AI training data claim",
            "check vendor privacy claim",
            "verify GDPR or DPA statement",
            "AI data clause evidence check",
        ],
        "request_type": "ai_data_clause",
    },
}


def _bazaar_extension(intent: dict) -> dict:
    example = {
        "vendor_url": "https://example.com/security",
        "claim": "Vendor states that customer data is encrypted at rest.",
        "vendor_name": "Example Vendor",
        "request_type": intent["request_type"],
    }
    return {
        "bazaar": {
            "info": {
                "input": {"type": "http", "method": "POST", "bodyType": "json", "body": example},
                "output": {"type": "json", "example": CLAIM_OUTPUT_EXAMPLE},
            },
            "schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "input": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "const": "http"},
                            "method": {"type": "string", "const": "POST"},
                            "bodyType": {"type": "string", "const": "json"},
                            "body": CLAIM_INPUT_SCHEMA,
                        },
                        "required": ["type", "method", "bodyType", "body"],
                    },
                    "output": {"type": "object"},
                },
                "required": ["input"],
            },
        }
    }


sales_routes = {}
for path, intent in SALES_INTENTS.items():
    sales_routes[f"POST {path}"] = RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to=PAY_TO, price=PRICE, network=NETWORK)],
        resource=f"{PUBLIC_ORIGIN}{path}",
        mime_type="application/json",
        description=intent["summary"],
        service_name=intent["service_name"],
        tags=intent["tags"],
        extensions=_bazaar_extension(intent),
    )

# A second payment middleware protects only the intent-specific aliases. The
# canonical middleware from app.py continues to protect /v1/claim-verify.
app.add_middleware(PaymentMiddlewareASGI, routes=sales_routes, server=server)


def _payment_info(path: str) -> dict:
    intent = SALES_INTENTS[path]
    return {
        "price": {"mode": "fixed", "currency": "USD", "amount": PRICE.lstrip("$")},
        "protocols": [{"x402": {"version": 2}}],
        "network": NETWORK,
        "asset": "USDC",
        "payTo": PAY_TO,
        "paymentHeader": "PAYMENT-SIGNATURE",
        "settlementHeader": "PAYMENT-RESPONSE",
        "buyerIntents": intent["buyer_queries"],
    }


def _openapi_extra(path: str) -> dict:
    intent = SALES_INTENTS[path]
    return {
        "x-price": PRICE,
        "x-x402-price": PRICE,
        "x-x402-network": NETWORK,
        "x-payment-info": _payment_info(path),
        "x-buyer-intents": intent["buyer_queries"],
        "x-bazaar-discoverable": True,
        "x-canonical-engine": "/v1/claim-verify",
        "x-input-schema": CLAIM_INPUT_SCHEMA,
    }


@app.get("/v1/buyer-catalog", tags=["discovery", "x402"])
def buyer_catalog():
    resources = []
    for path, intent in SALES_INTENTS.items():
        resources.append(
            {
                "name": intent["service_name"],
                "method": "POST",
                "url": f"{PUBLIC_ORIGIN}{path}",
                "path": path,
                "price": PRICE,
                "asset": "USDC",
                "network": NETWORK,
                "payTo": PAY_TO,
                "summary": intent["summary"],
                "tags": intent["tags"],
                "buyer_queries": intent["buyer_queries"],
                "input_schema": CLAIM_INPUT_SCHEMA,
            }
        )
    return {
        "service": "capi2 high-intent claim verification",
        "version": SERVICE_VERSION,
        "canonical": f"{PUBLIC_ORIGIN}/v1/claim-verify",
        "resources": resources,
        "payment_flow": "POST -> 402 PAYMENT-REQUIRED -> pay USDC on Base -> retry with PAYMENT-SIGNATURE -> 200 + PAYMENT-RESPONSE",
    }


@app.post(
    "/v1/vendor-security-check",
    response_model=ClaimVerifyResponse,
    tags=SALES_INTENTS["/v1/vendor-security-check"]["tags"],
    summary=SALES_INTENTS["/v1/vendor-security-check"]["summary"],
    description="Agent-native $0.01 x402 security/vendor evidence check. No account or API key required.",
    responses={402: {"description": "x402 payment required"}},
    openapi_extra=_openapi_extra("/v1/vendor-security-check"),
)
def vendor_security_check(payload: ClaimVerifyRequest):
    return _execute_claim_verify(payload)


@app.post(
    "/v1/procurement-claim-check",
    response_model=ClaimVerifyResponse,
    tags=SALES_INTENTS["/v1/procurement-claim-check"]["tags"],
    summary=SALES_INTENTS["/v1/procurement-claim-check"]["summary"],
    description="Agent-native $0.01 x402 procurement/SaaS evidence check. No account or API key required.",
    responses={402: {"description": "x402 payment required"}},
    openapi_extra=_openapi_extra("/v1/procurement-claim-check"),
)
def procurement_claim_check(payload: ClaimVerifyRequest):
    return _execute_claim_verify(payload)


@app.post(
    "/v1/data-clause-check",
    response_model=ClaimVerifyResponse,
    tags=SALES_INTENTS["/v1/data-clause-check"]["tags"],
    summary=SALES_INTENTS["/v1/data-clause-check"]["summary"],
    description="Agent-native $0.01 x402 AI-data/privacy evidence check. No account or API key required.",
    responses={402: {"description": "x402 payment required"}},
    openapi_extra=_openapi_extra("/v1/data-clause-check"),
)
def data_clause_check(payload: ClaimVerifyRequest):
    return _execute_claim_verify(payload)
