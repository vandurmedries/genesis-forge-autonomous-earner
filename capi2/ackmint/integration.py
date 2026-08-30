from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import core


def _remove_path(app: FastAPI, path: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) != path
    ]


def _service_listing() -> dict[str, Any]:
    listing: dict[str, Any] = {
        "service_id": "capi2.ackmint.v1",
        "name": core.NAME,
        "provider_type": "first_party",
        "offer_type": "api_service",
        "status": "active",
        "capabilities": [
            "reliable webhook delivery",
            "signed webhook receipt",
            "agent callback relay",
            "idempotent event delivery",
            "webhook retry",
            "callback delivery proof",
            "success-only delivery fee",
        ],
        "regulated_financial_execution": False,
        "discovery_url": f"{core.ORIGIN}/.well-known/x402",
        "quote_url": f"{core.ORIGIN}/v1/ackmint/pricing",
        "execute": {
            "method": "POST",
            "url": f"{core.ORIGIN}/v1/ackmint/relay/standard",
        },
        "payment": {
            "protocol": "x402",
            "asset": "USDC",
            "network": core.NETWORK,
            "price": "$0.02+",
            "amount": 0.02,
            "billing": "per_successful_delivery",
        },
        "result": {
            "mode": "inline",
            "content_type": "application/json",
            "proof": (
                f"Ed25519-signed delivery receipt retained for "
                f"{core.RETENTION_DAYS} days"
            ),
        },
        "commercial_notes": [
            "callback-domain proof is required",
            "private and local network targets are blocked",
            "the receiver must opt in",
            "no unauthorized installation or access",
        ],
    }
    if core.SETUP_URL:
        listing["setup_service"] = {
            "price": "€49 one-time",
            "url": core.SETUP_URL,
            "scope": "one authorized webhook or agent callback",
        }
    return listing


def _install_payment_middleware(app: FastAPI) -> None:
    if core.PAYMENTS_OFF:
        return

    from x402.extensions.bazaar import (
        OutputConfig,
        declare_discovery_extension,
    )
    from x402.http import (
        FacilitatorConfig,
        HTTPFacilitatorClient,
        PaymentOption,
    )
    from x402.http.middleware.fastapi import PaymentMiddlewareASGI
    from x402.http.types import RouteConfig
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.server import x402ResourceServer

    facilitator = HTTPFacilitatorClient(
        FacilitatorConfig(url=core.FACILITATOR)
    )
    server = x402ResourceServer(facilitator)
    server.register(core.NETWORK, ExactEvmServerScheme())

    input_example = {
        "integration_token": "<signed-token-from-integration-verify>",
        "event_id": "order_123",
        "event_type": "order.fulfilled",
        "source": "urn:shop:example",
        "payload": {"order_id": "123", "status": "fulfilled"},
        "idempotency_key": "order_123_fulfilled",
    }
    input_schema = {
        "type": "object",
        "properties": {
            "integration_token": {"type": "string"},
            "event_id": {"type": "string"},
            "event_type": {"type": "string"},
            "source": {"type": "string"},
            "payload": {},
            "idempotency_key": {"type": "string"},
        },
        "required": [
            "integration_token",
            "event_id",
            "event_type",
            "payload",
        ],
        "additionalProperties": False,
    }
    output_example = {
        "protocol": core.PROTOCOL,
        "status": "delivered",
        "tier": "standard",
        "receipt": {
            "payload": {
                "receipt_id": "rcpt_example",
                "status": "delivered",
            },
            "attestation": {
                "algorithm": "Ed25519",
                "signature_b64": "<signature>",
            },
        },
    }

    routes: dict[str, RouteConfig] = {}
    for tier_name, tier in core.TIERS.items():
        routes[f"POST {tier['path']}"] = RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to=core.PAY_TO,
                    price=tier["price"],
                    network=core.NETWORK,
                )
            ],
            resource=f"{core.ORIGIN}{tier['path']}",
            mime_type="application/json",
            description=(
                f"{core.NAME} {tier_name}: authorized webhook delivery "
                "with a signed persistent receipt."
            ),
            service_name=core.NAME,
            tags=[
                "webhook",
                "delivery-proof",
                "idempotency",
                "retries",
                "agents",
            ],
            extensions=declare_discovery_extension(
                input=input_example,
                input_schema=input_schema,
                body_type="json",
                output=OutputConfig(example=output_example),
            ),
        )
    app.add_middleware(
        PaymentMiddlewareASGI,
        routes=routes,
        server=server,
    )


def install(app: FastAPI, marketplace: Any) -> FastAPI:
    if getattr(app.state, "ackmint_installed", False):
        return app
    app.state.ackmint_installed = True

    if not any(
        item.get("service_id") == "capi2.ackmint.v1"
        for item in marketplace.FIRST_PARTY_SERVICES
    ):
        marketplace.FIRST_PARTY_SERVICES.insert(1, _service_listing())

    _install_payment_middleware(app)

    @app.on_event("startup")
    def init_ackmint_db() -> None:
        try:
            core.init_db()
        except Exception as exc:
            print(
                "AckMint database init deferred: "
                f"{exc.__class__.__name__}: {exc}"
            )

    _remove_path(app, "/")
    _remove_path(app, "/.well-known/agent.json")

    @app.get("/", response_class=HTMLResponse)
    async def ackmint_home() -> str:
        setup = ""
        if core.SETUP_URL:
            setup = (
                '<div class="card"><strong>Need help integrating?</strong><br>'
                f'<a href="{core.SETUP_URL}">Book one authorized webhook '
                'setup for €49</a>.</div>'
            )
        return f"""
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width,initial-scale=1">
          <title>{core.NAME} — paid webhook delivery proof</title>
          <style>
            body {{ font-family: system-ui, sans-serif; max-width: 820px;
                    margin: 56px auto; padding: 0 20px; line-height: 1.55; }}
            code {{ background: #f2f2f2; padding: 2px 5px;
                    border-radius: 4px; }}
            .card {{ border: 1px solid #ddd; border-radius: 12px;
                     padding: 20px; margin: 18px 0; }}
          </style>
        </head>
        <body>
          <h1>{core.NAME}</h1>
          <p>Opt-in reliability infrastructure for webhooks and AI-agent
             callbacks. Integrate once, then pay for a successful delivery.</p>
          <div class="card">
            <strong>Standard $0.02</strong> ·
            <strong>Assured $0.08</strong> ·
            <strong>Critical $0.25</strong>
          </div>
          <p>Each success returns an Ed25519-signed delivery receipt retained
             in PostgreSQL for {core.RETENTION_DAYS} days. Callback-domain proof
             is required; local and private targets are blocked.</p>
          <p><a href="/docs">API docs</a> ·
             <a href="/v1/ackmint/pricing">pricing JSON</a> ·
             <a href="/.well-known/x402">x402 discovery</a> ·
             <a href="/v1/services">marketplace catalog</a> ·
             <a href="/llms.txt">LLM notes</a></p>
          {setup}
        </body>
        </html>
        """

    @app.get("/llms.txt", response_class=PlainTextResponse)
    async def ackmint_llms() -> str:
        setup = (
            f"Human integration setup: {core.SETUP_URL}\n"
            if core.SETUP_URL
            else ""
        )
        return (
            f"# {core.NAME}\n\n"
            "Authorized, opt-in webhook and AI-agent callback delivery.\n"
            "The callback owner proves control of its public HTTPS domain. "
            "Private-network and local targets are blocked.\n\n"
            f"Origin: {core.ORIGIN}\n"
            f"Protocol: {core.PROTOCOL}\n"
            f"Payment: x402, USDC, {core.NETWORK}\n"
            "Prices: standard $0.02; assured $0.08; critical $0.25 per "
            "successful route handler.\n"
            "Discovery: /.well-known/x402\n"
            "Pricing: /v1/ackmint/pricing\n"
            "Onboarding: POST /v1/ackmint/integrations/challenge then POST "
            "/v1/ackmint/integrations/verify\n"
            "Paid delivery: POST /v1/ackmint/relay/standard, /assured, or "
            "/critical\n"
            "Receipt verification: POST /v1/ackmint/receipts/verify\n"
            f"{setup}"
            "No unauthorized installation, credential collection, or private "
            "network access is supported.\n"
        )

    @app.get("/.well-known/agent.json")
    async def ackmint_agent_manifest() -> dict[str, Any]:
        base = await marketplace.agent_manifest()
        base = dict(base)
        base["protocol"] = "capi2.marketplace/0.4"
        base["description"] = (
            "Discover CAPI2 services and invoke AckMint for authorized, "
            "paid webhook and agent-callback delivery."
        )
        endpoints = dict(base.get("endpoints", {}))
        endpoints["ackmint"] = {
            "pricing": {
                "method": "GET",
                "path": "/v1/ackmint/pricing",
            },
            "challenge": {
                "method": "POST",
                "path": "/v1/ackmint/integrations/challenge",
            },
            "verify": {
                "method": "POST",
                "path": "/v1/ackmint/integrations/verify",
            },
            "x402_discovery": {
                "method": "GET",
                "path": "/.well-known/x402",
            },
        }
        base["endpoints"] = endpoints
        return base

    @app.get("/.well-known/x402")
    async def ackmint_x402_manifest() -> dict[str, Any]:
        return {
            "name": core.NAME,
            "protocol": "x402",
            "service_protocol": core.PROTOCOL,
            "description": (
                "Authorized webhook and agent-callback delivery with "
                "persistent signed receipts."
            ),
            "network": core.NETWORK,
            "asset": "USDC",
            "payTo": core.PAY_TO,
            "resources": [
                {
                    "method": "POST",
                    "resource": f"{core.ORIGIN}{tier['path']}",
                    "price": tier["price"],
                    "attempts": tier["attempts"],
                    "explicit_ack_required": tier["ack"],
                    "success_only": True,
                }
                for tier in core.TIERS.values()
            ],
            "onboarding": {
                "challenge": (
                    f"{core.ORIGIN}/v1/ackmint/integrations/challenge"
                ),
                "verify": f"{core.ORIGIN}/v1/ackmint/integrations/verify",
                "proof_file": (
                    "https://<callback-host>/.well-known/ackmint.json"
                ),
            },
            "safety": {
                "authorized_opt_in_only": True,
                "domain_proof_required": True,
                "private_targets_blocked": True,
                "redirects_blocked": True,
            },
        }

    @app.get("/v1/ackmint/health")
    async def ackmint_health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "capi2-ackmint",
            "version": core.VERSION,
            "origin": core.ORIGIN,
            "payment_enforced": not core.PAYMENTS_OFF,
            "persistent_storage_configured": bool(core.DATABASE_URL),
            "network": core.NETWORK,
            "asset": "USDC",
            "pay_to": core.PAY_TO,
            "key_id": core.KID,
            "retention_days": core.RETENTION_DAYS,
        }

    @app.get("/v1/ackmint/pricing")
    async def ackmint_pricing() -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": core.NAME,
            "protocol": core.PROTOCOL,
            "billing": "per_successful_delivery",
            "payment_protocol": "x402",
            "network": core.NETWORK,
            "asset": "USDC",
            "pay_to": core.PAY_TO,
            "tiers": core.TIERS,
            "retention_days": core.RETENTION_DAYS,
            "onboarding": {
                "challenge": "/v1/ackmint/integrations/challenge",
                "verify": "/v1/ackmint/integrations/verify",
            },
        }
        if core.SETUP_URL:
            result["setup_service"] = {
                "price": "€49 one-time",
                "url": core.SETUP_URL,
                "scope": "one authorized webhook or agent callback",
            }
        return result

    @app.get("/v1/ackmint/public-key")
    async def ackmint_public_key() -> dict[str, Any]:
        return {
            "algorithm": "Ed25519",
            "key_id": core.KID,
            "public_key_b64": core.PUB,
        }

    @app.get("/v1/ackmint/stats")
    async def ackmint_stats() -> dict[str, Any]:
        try:
            stats = await asyncio.to_thread(core.stats_sync)
        except Exception as exc:
            raise HTTPException(
                503,
                f"ackmint_stats_unavailable:{exc.__class__.__name__}",
            ) from exc
        return {
            "protocol": core.PROTOCOL,
            **stats,
            "revenue_claim": (
                "No revenue is inferred from delivery rows; verify "
                "Payment-Response and on-chain settlements."
            ),
        }

    @app.post("/v1/ackmint/integrations/challenge")
    async def ackmint_challenge(request: core.ChallengeIn) -> dict[str, Any]:
        callback_url, host = await core.validate_url(request.callback_url)
        now = int(time.time())
        nonce = core.b64e(secrets.token_bytes(24))
        claims = {
            "iss": core.ORIGIN,
            "use": "challenge",
            "iat": now,
            "exp": now + 1800,
            "callback_url": callback_url,
            "host": host,
            "service_name": request.service_name,
            "ttl_days": request.integration_ttl_days,
            "nonce": nonce,
        }
        return {
            "status": "proof_required",
            "challenge_token": core.mint(claims, "ACKMINT-CHALLENGE"),
            "proof_url": f"https://{host}/.well-known/ackmint.json",
            "publish_exact_json": {
                "issuer": core.ORIGIN,
                "challenge": nonce,
                "callback_url": callback_url,
            },
        }

    @app.post("/v1/ackmint/integrations/verify")
    async def ackmint_verify(request: core.VerifyIn) -> dict[str, Any]:
        challenge = core.read_token(
            request.challenge_token,
            "ACKMINT-CHALLENGE",
        )
        if challenge.get("use") != "challenge":
            raise HTTPException(401, "not_a_challenge")
        callback_url, host = await core.validate_url(
            str(challenge["callback_url"])
        )
        expected = {
            "issuer": core.ORIGIN,
            "challenge": challenge["nonce"],
            "callback_url": callback_url,
        }
        found = await core.domain_proof(host)
        if any(found.get(key) != value for key, value in expected.items()):
            raise HTTPException(422, "proof_file_contents_mismatch")
        now = int(time.time())
        integration_id = "int_" + hashlib.sha256(
            (
                f"{host}|{callback_url}|"
                f"{challenge['service_name']}"
            ).encode()
        ).hexdigest()[:24]
        claims = {
            "iss": core.ORIGIN,
            "use": "integration",
            "iat": now,
            "exp": now + int(challenge["ttl_days"]) * 86400,
            "integration_id": integration_id,
            "service_name": challenge["service_name"],
            "host": host,
            "callback_url": callback_url,
            "tiers": list(core.TIERS),
        }
        return {
            "status": "verified",
            "integration_id": integration_id,
            "callback_url": callback_url,
            "integration_token": core.mint(
                claims,
                "ACKMINT-INTEGRATION",
            ),
            "public_key_url": f"{core.ORIGIN}/v1/ackmint/public-key",
        }

    @app.post("/v1/ackmint/receipts/verify")
    async def ackmint_verify_receipt(
        request: core.ReceiptIn,
    ) -> dict[str, Any]:
        return {
            "protocol": core.PROTOCOL,
            "valid": core.receipt_valid(request.receipt),
            "key_id": core.KID,
        }

    @app.post("/v1/ackmint/relay/status")
    async def ackmint_status(request: core.StatusIn) -> JSONResponse:
        item = core.integration(request.integration_token)
        idem = request.idempotency_key or request.event_id
        key = core.storage_key(item["integration_id"], idem)
        result = await core.get(key)
        if result is None:
            raise HTTPException(404, "receipt_not_found")
        if result["status"] == "processing":
            return JSONResponse(
                status_code=202,
                content={
                    "protocol": core.PROTOCOL,
                    "status": "processing",
                    "event_id": request.event_id,
                },
            )
        return JSONResponse(
            content={
                "protocol": core.PROTOCOL,
                "status": "delivered",
                "receipt": result["receipt"],
                "retained_until": result["expires_at"].isoformat(),
            }
        )

    async def relay(tier_name: str, request: core.RelayIn) -> dict[str, Any]:
        item = core.integration(request.integration_token)
        if tier_name not in item["tiers"]:
            raise HTTPException(403, "tier_not_allowed")
        callback_url, host = await core.validate_url(item["callback_url"])
        if host != item["host"]:
            raise HTTPException(401, "integration_host_mismatch")
        idem = request.idempotency_key or request.event_id
        event = {
            "specversion": "1.0",
            "id": request.event_id,
            "source": request.source,
            "type": request.event_type,
            "time": core.now_iso(),
            "datacontenttype": "application/json",
            "data": request.payload,
            "ackmint": {
                "protocol": core.PROTOCOL,
                "integration_id": item["integration_id"],
                "tier": tier_name,
            },
        }
        body = core.canon(event)
        if len(body) > core.MAX_BODY:
            raise HTTPException(413, "event_payload_too_large")
        key = core.storage_key(item["integration_id"], idem)
        reservation = await core.reserve(
            key=key,
            integration_id=item["integration_id"],
            event_id=request.event_id,
            idempotency_key=idem,
            event_type=request.event_type,
            tier=tier_name,
            body_sha256=hashlib.sha256(body).hexdigest(),
            callback_host=host,
        )
        if reservation["state"] == "delivered":
            raise HTTPException(
                409,
                {
                    "code": "already_delivered",
                    "fee_settlement": "cancelled_for_duplicate",
                    "receipt": reservation["receipt"],
                },
            )
        if reservation["state"] == "processing":
            raise HTTPException(
                409,
                {
                    "code": "delivery_in_progress",
                    "fee_settlement": "cancelled",
                },
            )
        lease_token = reservation["lease_token"]
        try:
            status_code, attempts, response_hash, attempt_log = (
                await core.deliver(
                    tier_name,
                    callback_url,
                    request.event_id,
                    idem,
                    body,
                )
            )
        except HTTPException:
            await core.release(key, lease_token)
            raise
        receipt_payload = {
            "protocol": core.PROTOCOL,
            "receipt_id": "rcpt_" + secrets.token_hex(16),
            "status": "delivered",
            "integration_id": item["integration_id"],
            "event_id": request.event_id,
            "idempotency_key": idem,
            "event_type": request.event_type,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "callback_host": host,
            "callback_status_code": status_code,
            "callback_response_sha256": response_hash,
            "attempts": attempts,
            "attempt_log": attempt_log,
            "delivered_at": core.now_iso(),
            "retained_until": time.time() + core.RETENTION_DAYS * 86400,
            "fee": {
                "display": core.TIERS[tier_name]["price"],
                "protocol": "x402",
                "asset": "USDC",
                "network": core.NETWORK,
                "settlement": "after_successful_route_handler",
            },
        }
        receipt = core.signed_receipt(receipt_payload)
        await core.complete(key, lease_token, receipt)
        return {
            "protocol": core.PROTOCOL,
            "status": "delivered",
            "tier": tier_name,
            "receipt": receipt,
            "payment_receipt": (
                "Read the Payment-Response response header and verify the "
                "returned transaction independently."
            ),
        }

    @app.post("/v1/ackmint/relay/standard")
    async def ackmint_standard(request: core.RelayIn) -> dict[str, Any]:
        return await relay("standard", request)

    @app.post("/v1/ackmint/relay/assured")
    async def ackmint_assured(request: core.RelayIn) -> dict[str, Any]:
        return await relay("assured", request)

    @app.post("/v1/ackmint/relay/critical")
    async def ackmint_critical(request: core.RelayIn) -> dict[str, Any]:
        return await relay("critical", request)

    return app
