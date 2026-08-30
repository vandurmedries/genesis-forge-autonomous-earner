from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any

from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

# Reuse the audited relay core from the predecessor branch, but generate a
# distinct CAPI2 RelayLock protocol namespace and proof path at import time.
_core_path = Path(__file__).resolve().parents[1] / "receiptrail" / "app.py"
_source = _core_path.read_text(encoding="utf-8")
for old, new in (
    ("CAPI2 ReceiptRail", "CAPI2 RelayLock"),
    ("capi2.receiptrail/1.0", "capi2.relaylock/1.0"),
    ("CAPI2_RECEIPTRAIL_", "CAPI2_RELAYLOCK_"),
    ("capi2-receiptrail.onrender.com", "capi2-relaylock.onrender.com"),
    ("capi2-receiptrail.json", "capi2-relaylock.json"),
    ("capi2-receiptrail", "capi2-relaylock"),
    ("CAPI2-CHALLENGE", "CAPI2-RELAYLOCK-CHALLENGE"),
    ("CAPI2-INTEGRATION", "CAPI2-RELAYLOCK-INTEGRATION"),
):
    _source = _source.replace(old, new)

_ns: dict[str, Any] = {
    "__name__": "capi2.relaylock._core",
    "__file__": str(_core_path),
    "__package__": "capi2.relaylock",
}
exec(compile(_source, str(_core_path), "exec"), _ns)

app = _ns["app"]
ORIGIN: str = _ns["ORIGIN"]
PAY_TO: str = _ns["PAY_TO"]
NETWORK: str = _ns["NETWORK"]
PUB: str = _ns["PUB"]
KID: str = _ns["KID"]
TIERS: dict[str, dict[str, Any]] = _ns["TIERS"]
PAYMENTS_OFF: bool = _ns["PAYMENTS_OFF"]
validate_url = _ns["validate_url"]

SETUP_URL = os.getenv(
    "CAPI2_RELAYLOCK_SETUP_URL",
    "https://book.stripe.com/aFa8wQ5xr6KJbXwg8Z5Vu0l",
).strip()
SOURCE_URL = (
    "https://github.com/vandurmedries/genesis-forge-autonomous-earner/"
    "tree/product/capi2-relaylock-v1/capi2/relaylock"
)

app.title = "CAPI2 RelayLock"
app.description = (
    "Opt-in reliability layer for webhooks and agent callbacks. "
    "x402 usage fees are tied to successful callback delivery."
)


def _drop_get(path: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and "GET" in (getattr(route, "methods", set()) or set())
        )
    ]


for _path in ("/", "/health", "/v1/pricing"):
    _drop_get(_path)


LANDING = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CAPI2 RelayLock — successful-delivery fees</title>
<style>
:root{{color-scheme:dark;--muted:#a9b5cf;--line:#253252}}
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,system-ui,sans-serif;background:linear-gradient(145deg,#080c18,#111a33);color:#f7f9ff}}
main{{max-width:980px;margin:auto;padding:72px 22px 80px}}h1{{font-size:clamp(44px,8vw,78px);line-height:.96;letter-spacing:-.04em;margin:22px 0}}
p{{color:var(--muted);line-height:1.55}}.lead{{max-width:760px;font-size:21px}}.badge{{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:8px 12px;color:#9dbdff}}
.actions{{display:flex;gap:12px;flex-wrap:wrap;margin:30px 0 50px}}a.button{{text-decoration:none;color:#081020;background:#dbe7ff;padding:13px 18px;border-radius:12px;font-weight:750}}a.alt{{color:#eef3ff;background:#18233d;border:1px solid var(--line)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}}.card{{background:#131a2de8;border:1px solid var(--line);padding:22px;border-radius:18px}}.price{{font-size:30px;font-weight:800}}pre{{overflow:auto;padding:18px;border-radius:14px;background:#080d1b;border:1px solid var(--line);color:#d9e5ff}}section,footer{{margin-top:52px}}
</style></head><body><main>
<span class="badge">CAPI2 infrastructure · authorized integration only</span>
<h1>Make critical callbacks harder to lose.</h1>
<p class="lead">RelayLock sits between an authorized sender and its callback. It adds controlled retries, idempotency headers, signed events and a portable delivery receipt. The machine fee is charged through x402 only after the callback succeeds.</p>
<div class="actions"><a class="button" href="{html.escape(SETUP_URL)}">Book the €39 integration pilot</a><a class="button alt" href="/docs">API docs</a><a class="button alt" href="/v1/quickstart">Machine quickstart</a></div>
<div class="grid"><div class="card"><h2>Standard</h2><div class="price">$0.02</div><p>One delivery attempt.</p></div><div class="card"><h2>Assured</h2><div class="price">$0.10</div><p>Up to four attempts.</p></div><div class="card"><h2>Critical</h2><div class="price">$0.50</div><p>Up to five attempts plus explicit receiver acknowledgement.</p></div></div>
<section><h2>One integration point</h2><pre>your system → CAPI2 RelayLock → verified callback → signed receipt</pre><p>Only public HTTPS callbacks are accepted. Domain control must be proven. Local/private targets, IP literals and redirects are blocked.</p></section>
<section class="grid"><div class="card"><h2>Portable proof</h2><p>Receipts are self-contained Ed25519 attestations. Store them in your own system and verify them later.</p></div><div class="card"><h2>Duplicate defence</h2><p>RelayLock blocks recent duplicate delivery keys. Receivers must durably enforce the supplied idempotency key.</p></div><div class="card"><h2>No hidden installation</h2><p>An owner must explicitly integrate RelayLock and prove control of the destination domain.</p></div></section>
<footer><p>The €39 pilot covers one callback path, one implementation snippet and one end-to-end test. Ongoing x402 fees are separate. No uptime, revenue, savings or legal-compliance guarantee.</p><p><a href="/terms" style="color:#bcd0ff">Terms</a> · <a href="/privacy" style="color:#bcd0ff">Privacy</a> · <a href="{SOURCE_URL}" style="color:#bcd0ff">Source</a></p></footer>
</main></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def landing() -> str:
    return LANDING


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "capi2-relaylock",
        "version": "1.0.0",
        "origin": ORIGIN,
        "payment_enforced": not PAYMENTS_OFF,
        "network": NETWORK,
        "asset": "USDC",
        "pay_to": PAY_TO,
        "key_id": KID,
        "receipt_model": "portable_self_contained_signature",
        "duplicate_model": "24h_hot_guard_plus_receiver_idempotency",
    }


@app.get("/v1/pricing")
async def pricing() -> dict[str, Any]:
    return {
        "protocol": "capi2.relaylock/1.0",
        "rule": "x402 fee is tied to successful callback delivery",
        "network": NETWORK,
        "asset": "USDC",
        "pay_to": PAY_TO,
        "tiers": TIERS,
        "integration_pilot": {
            "price": "€39",
            "billing": "one_time",
            "url": SETUP_URL,
            "scope": [
                "one callback path",
                "one implementation snippet",
                "one end-to-end test",
                "one signed receipt",
            ],
        },
    }


class CallbackCheck(BaseModel):
    callback_url: str = Field(min_length=12, max_length=2048)


@app.post("/v1/check-callback")
async def check_callback(request: CallbackCheck) -> dict[str, Any]:
    callback_url, host = await validate_url(request.callback_url)
    return {
        "status": "eligible_for_domain_proof",
        "callback_url": callback_url,
        "host": host,
        "proof_url": f"https://{host}/.well-known/capi2-relaylock.json",
    }


@app.get("/v1/quickstart")
async def quickstart() -> dict[str, Any]:
    return {
        "protocol": "capi2.relaylock/1.0",
        "origin": ORIGIN,
        "flow": [
            "POST /v1/integrations/challenge with callback_url and service_name",
            "publish the returned exact JSON at /.well-known/capi2-relaylock.json",
            "POST /v1/integrations/verify with challenge_token",
            "use an x402 payment-aware client to POST an event to /v1/relay/{tier}",
            "store the returned signed receipt and enforce idempotency at the receiver",
        ],
        "sdk": {
            "javascript": f"{ORIGIN}/sdk/javascript",
            "python": f"{ORIGIN}/sdk/python",
        },
        "pilot": SETUP_URL,
    }


@app.get("/sdk/javascript", response_class=PlainTextResponse)
async def javascript_sdk() -> str:
    return f'''// Inject an x402 payment-aware fetch implementation for paid calls.
export const relayLock = (fetchWithPay, origin = "{ORIGIN}") => {{
  const post = async (path, body) => {{
    const r = await fetchWithPay(origin + path, {{method:"POST",headers:{{"content-type":"application/json"}},body:JSON.stringify(body)}});
    const data = await r.json(); if (!r.ok) throw new Error(JSON.stringify(data)); return data;
  }};
  return {{
    challenge: (callback_url, service_name) => post("/v1/integrations/challenge", {{callback_url, service_name}}),
    verify: (challenge_token) => post("/v1/integrations/verify", {{challenge_token}}),
    send: (tier, event) => post(`/v1/relay/${{tier}}`, event),
    verifyReceipt: (receipt) => post("/v1/receipts/verify", {{receipt}}),
  }};
}};
'''


@app.get("/sdk/python", response_class=PlainTextResponse)
async def python_sdk() -> str:
    return f'''# Inject an x402 payment-aware httpx-compatible client for paid calls.
class RelayLock:
    def __init__(self, client, origin="{ORIGIN}"):
        self.client, self.origin = client, origin.rstrip("/")
    async def post(self, path, body):
        r = await self.client.post(self.origin + path, json=body); r.raise_for_status(); return r.json()
    async def challenge(self, callback_url, service_name):
        return await self.post("/v1/integrations/challenge", {{"callback_url": callback_url, "service_name": service_name}})
    async def verify(self, challenge_token):
        return await self.post("/v1/integrations/verify", {{"challenge_token": challenge_token}})
    async def send(self, tier, event):
        return await self.post(f"/v1/relay/{{tier}}", event)
'''


@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt() -> str:
    return f'''# CAPI2 RelayLock
Opt-in webhook and agent-callback reliability layer.
Origin: {ORIGIN}
Discovery: {ORIGIN}/.well-known/agent.json
x402 manifest: {ORIGIN}/.well-known/x402
Quickstart: {ORIGIN}/v1/quickstart
OpenAPI: {ORIGIN}/openapi.json
Integration pilot: {SETUP_URL}
Fees: Standard $0.02, Assured $0.10, Critical $0.50 per successful delivery.
Never target a system without authorization. Domain control is required.
'''


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> str:
    return "User-agent: *\nAllow: /\n"


@app.get("/terms", response_class=HTMLResponse)
async def terms() -> str:
    return """<!doctype html><meta charset=utf-8><main style='max-width:760px;margin:50px auto;font:17px system-ui;line-height:1.65;padding:0 20px'><h1>CAPI2 RelayLock terms</h1><p>Use is limited to systems and callback endpoints the integrator owns or is authorized to operate.</p><p>The pilot covers one callback path, one implementation snippet and one end-to-end test. Ongoing x402 fees are separate.</p><p>No uptime, delivery, revenue, savings, certification or legal-compliance guarantee is made. The receiver must enforce idempotency and retain its own receipts.</p><p>Unauthorized probing, private-network targeting and domain-proof bypass attempts are prohibited.</p></main>"""


@app.get("/privacy", response_class=HTMLResponse)
async def privacy() -> str:
    return """<!doctype html><meta charset=utf-8><main style='max-width:760px;margin:50px auto;font:17px system-ui;line-height:1.65;padding:0 20px'><h1>CAPI2 RelayLock privacy</h1><p>RelayLock processes callback configuration, event metadata and payloads to perform the requested delivery. Recent delivery keys and receipts are held briefly in volatile memory for duplicate protection.</p><p>Do not transmit unnecessary personal data, secrets, card data, health data or credentials in event payloads.</p><p>Stripe processes checkout data for the optional integration pilot under its own terms.</p></main>"""
