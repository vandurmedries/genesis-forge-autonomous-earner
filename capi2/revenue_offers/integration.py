from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

ORIGIN = "https://capi2-agent-marketplace-router.onrender.com"
AUDIT_URL = "https://book.stripe.com/aFaeVe1hb4CB5z8e0R5Vu0o"
FIX_SPRINT_URL = "https://book.stripe.com/eVq5kEf817ON4v4e0R5Vu0p"
ACKMINT_SETUP_URL = "https://book.stripe.com/3cIfZiaRL8SRd1A6yp5Vu0m"
APIFY_INTELLIGENCE_URL = "https://apify.com/capi2/my-actor"
APIFY_BUYER_SIGNALS_URL = "https://apify.com/capi2/my-actor-1"

OFFERS: list[dict[str, Any]] = [
    {
        "service_id": "capi2.webhook-revenue-leak-audit.v1",
        "name": "Webhook & API Revenue Leak Audit",
        "offer_type": "professional_service",
        "status": "active",
        "price": {"currency": "EUR", "amount": 99.0, "billing": "one_time"},
        "checkout_url": AUDIT_URL,
        "scope": {
            "included": [
                "one customer-owned public API, webhook, payment callback, or agent event flow",
                "reproducible tests and failure-path analysis",
                "written root-cause report",
                "prioritized remediation plan",
                "one follow-up review",
            ],
            "excluded": [
                "implementation",
                "penetration testing",
                "compliance certification",
                "ongoing monitoring",
                "uptime, platform-approval, or revenue guarantees",
            ],
        },
        "authorization_required": True,
        "secret_collection_at_checkout": False,
    },
    {
        "service_id": "capi2.webhook-fix-sprint.v1",
        "name": "Webhook Fix Sprint",
        "offer_type": "professional_service",
        "status": "active",
        "price": {"currency": "EUR", "amount": 299.0, "billing": "one_time"},
        "checkout_url": FIX_SPRINT_URL,
        "scope": {
            "included": [
                "one customer-owned or authorized repository",
                "one agreed API, webhook, payment callback, or agent event flow",
                "agreed idempotency, retry, signature, or callback fixes",
                "deployment guidance",
                "one production smoke test",
            ],
            "excluded": [
                "broad rewrites or unrelated bugs",
                "third-party charges",
                "ongoing support",
                "uptime, platform-approval, or revenue guarantees",
            ],
        },
        "authorization_required": True,
        "secret_collection_at_checkout": False,
    },
    {
        "service_id": "capi2.ackmint-setup.v1",
        "name": "AckMint Webhook Integration Setup",
        "offer_type": "professional_service",
        "status": "active",
        "price": {"currency": "EUR", "amount": 49.0, "billing": "one_time"},
        "checkout_url": ACKMINT_SETUP_URL,
        "scope": {
            "included": [
                "one authorized webhook or AI-agent callback",
                "callback-domain verification guidance",
                "one configured and tested event flow",
                "signed receipt verification check",
            ],
            "excluded": [
                "ongoing development or hosting",
                "per-delivery x402 fees",
                "uptime, platform-approval, or revenue guarantees",
            ],
        },
        "authorization_required": True,
        "secret_collection_at_checkout": False,
    },
]


def _remove_path(app: FastAPI, path: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) != path
    ]


def _listing(offer: dict[str, Any]) -> dict[str, Any]:
    price = offer["price"]
    return {
        "service_id": offer["service_id"],
        "name": offer["name"],
        "provider_type": "first_party",
        "offer_type": offer["offer_type"],
        "status": offer["status"],
        "capabilities": offer["scope"]["included"],
        "regulated_financial_execution": False,
        "quote_url": f"{ORIGIN}/v1/offers",
        "execute": {
            "method": "GET",
            "url": offer["checkout_url"],
            "mode": "human_checkout",
        },
        "payment": {
            "protocol": "stripe_payment_link",
            "currency": price["currency"],
            "amount": price["amount"],
            "billing": price["billing"],
        },
        "result": {
            "mode": "human_fulfilled",
            "scope": offer["scope"],
        },
        "commercial_notes": [
            "customer authorization is required",
            "do not submit credentials or secrets at checkout",
            "no uptime, approval, or revenue guarantee",
        ],
    }


def install(app: FastAPI, marketplace: Any) -> FastAPI:
    if getattr(app.state, "revenue_offers_installed", False):
        return app
    app.state.revenue_offers_installed = True

    existing = {
        item.get("service_id")
        for item in marketplace.FIRST_PARTY_SERVICES
        if isinstance(item, dict)
    }
    for offer in reversed(OFFERS):
        if offer["service_id"] not in existing:
            marketplace.FIRST_PARTY_SERVICES.insert(0, _listing(offer))

    @app.get("/v1/offers")
    async def list_offers() -> dict[str, Any]:
        return {
            "name": "CAPI2 commercial offers",
            "origin": ORIGIN,
            "status": "active",
            "offers": OFFERS,
            "machine_services": {
                "ackmint_pricing": f"{ORIGIN}/v1/ackmint/pricing",
                "x402_discovery": f"{ORIGIN}/.well-known/x402",
            },
            "marketplace_products": [
                {
                    "name": "capi2 Agent Intelligence Toolkit",
                    "url": APIFY_INTELLIGENCE_URL,
                    "billing": "Apify pay per event",
                },
                {
                    "name": "Website Buyer Signal Scanner",
                    "url": APIFY_BUYER_SIGNALS_URL,
                    "billing": "Apify pay per event",
                },
            ],
            "revenue_status": (
                "Availability is not proof of a sale. Revenue is counted only "
                "after an independently verified completed payment."
            ),
        }

    @app.get("/.well-known/capi2-offers.json")
    async def offers_manifest() -> dict[str, Any]:
        return {
            "version": "1.0",
            "provider": "CAPI2",
            "origin": ORIGIN,
            "offers_endpoint": f"{ORIGIN}/v1/offers",
            "services": [
                {
                    "service_id": offer["service_id"],
                    "name": offer["name"],
                    "price": offer["price"],
                    "checkout_url": offer["checkout_url"],
                    "authorization_required": True,
                }
                for offer in OFFERS
            ],
        }

    @app.get("/offers", response_class=HTMLResponse)
    async def offers_page() -> str:
        return _home_html()

    _remove_path(app, "/")

    @app.get("/", response_class=HTMLResponse)
    async def commercial_home() -> str:
        return _home_html()

    return app


def _home_html() -> str:
    return f"""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>CAPI2 — reliable events, audits and fixes</title>
      <meta name="description" content="Paid webhook delivery, signed receipts, technical audits and fixed-scope webhook repairs.">
      <style>
        :root {{ color-scheme: light dark; }}
        body {{ font-family: system-ui, sans-serif; max-width: 980px;
                margin: 48px auto; padding: 0 20px; line-height: 1.55; }}
        h1 {{ font-size: clamp(2rem, 6vw, 4rem); margin-bottom: .2em; }}
        .lead {{ font-size: 1.15rem; max-width: 760px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(250px,1fr));
                 gap: 16px; margin: 28px 0; }}
        .card {{ border: 1px solid #9996; border-radius: 14px; padding: 20px; }}
        .price {{ font-size: 1.6rem; font-weight: 750; margin: .3rem 0; }}
        .button {{ display: inline-block; padding: 10px 14px; border-radius: 9px;
                   border: 1px solid currentColor; text-decoration: none;
                   font-weight: 650; margin-top: 8px; }}
        code {{ background: #8882; padding: 2px 5px; border-radius: 4px; }}
        .small {{ font-size: .9rem; opacity: .8; }}
      </style>
    </head>
    <body>
      <h1>CAPI2</h1>
      <p class="lead">Reliable webhook and AI-agent delivery, plus bounded
      technical audits and fixes for systems that lose events, retry badly,
      duplicate work, or fail after payment.</p>

      <h2>Buy a fixed-scope service</h2>
      <div class="grid">
        <section class="card">
          <h3>Revenue Leak Audit</h3>
          <div class="price">€99</div>
          <p>One authorized API, webhook, payment callback, or agent event
          flow. Reproducible tests, root-cause report, prioritized fixes, and
          one follow-up review.</p>
          <a class="button" href="{AUDIT_URL}">Book the audit</a>
        </section>
        <section class="card">
          <h3>Webhook Fix Sprint</h3>
          <div class="price">€299</div>
          <p>One authorized repository and one agreed event flow. Applicable
          idempotency, retry, signature, or callback fixes, deployment
          guidance, and one production smoke test.</p>
          <a class="button" href="{FIX_SPRINT_URL}">Book the sprint</a>
        </section>
        <section class="card">
          <h3>AckMint Setup</h3>
          <div class="price">€49</div>
          <p>Connect one authorized callback to AckMint, verify the domain,
          configure one event flow, and test signed receipt verification.</p>
          <a class="button" href="{ACKMINT_SETUP_URL}">Book integration</a>
        </section>
      </div>

      <h2>Pay per result</h2>
      <div class="grid">
        <section class="card">
          <h3>AckMint delivery</h3>
          <p><strong>$0.02 Standard</strong> · <strong>$0.08 Assured</strong> ·
          <strong>$0.25 Critical</strong>. Pay through x402 after a successful
          route handler; successful receipts are signed and persisted.</p>
          <a class="button" href="/docs">Open API docs</a>
        </section>
        <section class="card">
          <h3>Apify intelligence</h3>
          <p>Claim checks, evidence extraction, domain intelligence, public
          web lookup, API audits, and bulk website buyer-signal scans.</p>
          <a class="button" href="{APIFY_INTELLIGENCE_URL}">Intelligence Actor</a>
          <a class="button" href="{APIFY_BUYER_SIGNALS_URL}">Buyer signals</a>
        </section>
      </div>

      <p><a href="/v1/offers">offers JSON</a> ·
         <a href="/.well-known/capi2-offers.json">offers manifest</a> ·
         <a href="/.well-known/x402">x402 discovery</a> ·
         <a href="/.well-known/agent.json">agent manifest</a> ·
         <a href="/v1/services">service catalog</a></p>
      <p class="small">Authorized targets only. Do not put credentials or
      secrets into checkout fields. Services do not guarantee uptime,
      third-party approval, or revenue.</p>
    </body>
    </html>
    """
