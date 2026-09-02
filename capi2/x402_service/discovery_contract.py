"""Deterministic x402scan OpenAPI contract for the live capi2 seller surface.

This deliberately does not ask FastAPI/Pydantic to introspect every runtime-added
route. Repository-level guards add sandbox routes dynamically, and one of those
can carry deferred local annotations that are irrelevant to paid discovery but
can make generic OpenAPI generation fail. x402scan only needs a clean contract
for invocable payable resources, so publish that contract explicitly.
"""
from __future__ import annotations

from .app import (
    app,
    PAY_TO,
    PRICE,
    NETWORK,
    PUBLIC_ORIGIN,
    SERVICE_VERSION,
    CLAIM_INPUT_SCHEMA,
    CLAIM_OUTPUT_SCHEMA,
    CLAIM_OUTPUT_EXAMPLE,
)
from .sales_app import (
    DDQ_BUYER_QUERIES,
    DDQ_PATH,
    DDQ_PRICE,
    PACK_BUYER_QUERIES,
    PACK_PATH,
    PACK_PRICE,
    SALES_INTENTS,
)


_GENERIC_INTENT = {
    "service_name": "capi2 Claim Verify",
    "summary": "Verify a vendor, product, security, compliance, procurement or commercial claim against public evidence.",
    "tags": ["vendor verification", "due diligence", "procurement", "fact checking"],
    "buyer_queries": [
        "verify a vendor claim against public evidence",
        "fact check an AI vendor or SaaS claim",
        "procurement due diligence evidence",
        "vendor risk evidence check",
    ],
    "request_type": "claim_verify",
}


def _payment_info(intent: dict) -> dict:
    return {
        "price": {
            "mode": "fixed",
            "currency": "USD",
            "amount": PRICE.lstrip("$"),
        },
        "protocols": [{"x402": {}}],
        "network": NETWORK,
        "asset": "USDC",
        "payTo": PAY_TO,
        "paymentHeader": "PAYMENT-SIGNATURE",
        "settlementHeader": "PAYMENT-RESPONSE",
        "buyerIntents": intent["buyer_queries"],
    }


def _paid_operation(path: str, intent: dict) -> dict:
    operation_id = path.strip("/").replace("/", "_").replace("-", "_")
    example = {
        "vendor_url": "https://example.com",
        "claim": "Example Vendor states that customer data is encrypted at rest.",
        "vendor_name": "Example Vendor",
        "request_type": intent["request_type"],
    }
    return {
        "operationId": operation_id,
        "summary": intent["summary"],
        "description": (
            f"{intent['summary']} Costs {PRICE} USDC per successful paid call on Base. "
            "No account or API key is required. Call without payment to receive the x402 challenge, "
            "then retry the identical request with PAYMENT-SIGNATURE."
        ),
        "tags": intent["tags"],
        "x-payment-info": _payment_info(intent),
        "x-buyer-intents": intent["buyer_queries"],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": CLAIM_INPUT_SCHEMA,
                    "example": example,
                }
            },
        },
        "responses": {
            "200": {
                "description": "Successful evidence-backed verification result",
                "content": {
                    "application/json": {
                        "schema": CLAIM_OUTPUT_SCHEMA,
                        "example": CLAIM_OUTPUT_EXAMPLE,
                    }
                },
            },
            "402": {"description": "Payment Required"},
            "422": {"description": "Supplied public source or claim could not be processed"},
        },
    }


def build_openapi() -> dict:
    paths: dict[str, dict] = {
        "/v1/claim-verify": {"post": _paid_operation("/v1/claim-verify", _GENERIC_INTENT)},
        "/v1/commerce-receipts/issue": {
            "post": {
                "operationId": "issue_commerce_receipt",
                "summary": "Bind an agent purchase request and delivery into a portable receipt",
                "tags": ["commerce receipts", "agent commerce"],
                "x-payment-info": {"required": False},
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["request_id", "seller", "price", "asset", "network", "request", "delivery"],
                                "properties": {
                                    "request_id": {"type": "string"},
                                    "idempotency_key": {"type": "string"},
                                    "buyer_agent": {"type": "string"},
                                    "seller": {"type": "string"},
                                    "authority": {"type": "object"},
                                    "policy_decision": {"type": "object"},
                                    "price": {"type": "number", "minimum": 0},
                                    "asset": {"type": "string"},
                                    "network": {"type": "string"},
                                    "request": {"type": "object"},
                                    "delivery": {"type": "object"},
                                    "verification": {"type": "object"},
                                    "settlement": {"type": "object"},
                                    "issued_at": {"type": "string", "format": "date-time"},
                                },
                            }
                        }
                    },
                },
                "responses": {"200": {"description": "Canonical commerce receipt"}},
            }
        },
        "/v1/commerce-receipts/verify": {
            "post": {
                "operationId": "verify_commerce_receipt",
                "summary": "Verify commerce receipt hashes and optional Ed25519 signature",
                "tags": ["commerce receipts", "agent commerce"],
                "x-payment-info": {"required": False},
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"type": "object", "required": ["receipt"], "properties": {"receipt": {"type": "object"}}}}},
                },
                "responses": {"200": {"description": "Receipt integrity verdict"}},
            }
        },
        "/v1/commerce-receipts/signing-key": {
            "get": {
                "operationId": "get_commerce_receipt_signing_key",
                "summary": "Get the active Ed25519 receipt-verification key",
                "tags": ["commerce receipts", "agent commerce"],
                "x-payment-info": {"required": False},
                "responses": {"200": {"description": "Public signing-key metadata"}},
            }
        },
    }
    for path, intent in SALES_INTENTS.items():
        paths[path] = {"post": _paid_operation(path, intent)}
    pack_schema = {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "minItems": 2,
                "maxItems": 5,
                "items": CLAIM_INPUT_SCHEMA,
            }
        },
        "required": ["claims"],
    }
    paths[PACK_PATH] = {
        "post": {
            "operationId": "vendor_risk_pack",
            "summary": "Verify two to five vendor claims in one purchase",
            "description": f"Batch vendor due diligence for {PACK_PRICE} USDC on Base via x402.",
            "tags": ["vendor risk", "batch verification", "procurement"],
            "x-payment-info": {
                "price": {"mode": "fixed", "currency": "USD", "amount": PACK_PRICE.lstrip("$")},
                "protocols": [{"x402": {}}],
                "network": NETWORK,
                "asset": "USDC",
                "payTo": PAY_TO,
                "paymentHeader": "PAYMENT-SIGNATURE",
                "settlementHeader": "PAYMENT-RESPONSE",
                "buyerIntents": PACK_BUYER_QUERIES,
            },
            "x-buyer-intents": PACK_BUYER_QUERIES,
            "requestBody": {"required": True, "content": {"application/json": {"schema": pack_schema}}},
            "responses": {
                "200": {"description": "Batch verification results"},
                "402": {"description": "Payment Required"},
                "422": {"description": "Invalid pack or supplied source"},
            },
        }
    }
    ddq_schema = {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "minItems": 3,
                "maxItems": 10,
                "items": CLAIM_INPUT_SCHEMA,
            }
        },
        "required": ["claims"],
    }
    paths[DDQ_PATH] = {
        "post": {
            "operationId": "ai_vendor_ddq_evidence_pack",
            "summary": "Verify an AI vendor due-diligence evidence pack",
            "description": f"Verify three to ten AI-vendor claims for {DDQ_PRICE} USDC on Base via x402.",
            "tags": ["AI governance", "vendor due diligence", "procurement", "DDQ"],
            "x-payment-info": {
                "price": {"mode": "fixed", "currency": "USD", "amount": DDQ_PRICE.lstrip("$")},
                "protocols": [{"x402": {}}],
                "network": NETWORK,
                "asset": "USDC",
                "payTo": PAY_TO,
                "paymentHeader": "PAYMENT-SIGNATURE",
                "settlementHeader": "PAYMENT-RESPONSE",
                "buyerIntents": DDQ_BUYER_QUERIES,
            },
            "x-buyer-intents": DDQ_BUYER_QUERIES,
            "requestBody": {"required": True, "content": {"application/json": {"schema": ddq_schema}}},
            "responses": {
                "200": {
                    "description": "AI-vendor due-diligence evidence results",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "product": {"type": "string"},
                                    "claims_processed": {"type": "integer"},
                                    "supported": {"type": "integer"},
                                    "contradicted": {"type": "integer"},
                                    "uncertain": {"type": "integer"},
                                    "results": {
                                        "type": "array",
                                        "items": CLAIM_OUTPUT_SCHEMA,
                                    },
                                    "report_markdown": {"type": "string"},
                                },
                                "required": [
                                    "product", "claims_processed", "supported",
                                    "contradicted", "uncertain", "results", "report_markdown",
                                ],
                            }
                        }
                    },
                },
                "402": {"description": "Payment Required"},
                "422": {"description": "Invalid pack or supplied source"},
            },
        }
    }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "capi2 Claim Verify",
            "version": SERVICE_VERSION,
            "description": "Agent-native evidence-backed claim verification with x402 micropayments on Base USDC.",
            "x-guidance": (
                "Choose the route that matches the task: POST /v1/vendor-security-check for security/compliance claims, "
                "POST /v1/procurement-claim-check for SaaS/RFP/procurement claims, POST /v1/data-clause-check for "
                "AI-data/privacy/DPA claims, or POST /v1/claim-verify for the general case. Send JSON with vendor_url "
                "and claim. Each paid POST returns HTTP 402 when unpaid; pay the x402 v2 challenge in USDC on Base "
                "and retry the identical request with PAYMENT-SIGNATURE."
            ),
            "contact": {"email": "capi2@agentmail.to"},
        },
        "servers": [{"url": PUBLIC_ORIGIN}],
        "paths": paths,
    }


def install() -> None:
    def deterministic_openapi() -> dict:
        if app.openapi_schema is None or app.openapi_schema.get("x-capi2-static-discovery") is not True:
            schema = build_openapi()
            schema["x-capi2-static-discovery"] = True
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi_schema = None
    app.openapi = deterministic_openapi
    print(
        f"capi2-discovery-contract: installed routes={3 + len(SALES_INTENTS)} base_price={PRICE} pack_price={PACK_PRICE} ddq_price={DDQ_PRICE} origin={PUBLIC_ORIGIN}",
        flush=True,
    )


install()
