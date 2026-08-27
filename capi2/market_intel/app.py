from __future__ import annotations

import asyncio
import hmac
import html
import json
import os
import time
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field

from .core import TAXONOMY, build_intelligence, build_launch_brief, extract_items, public_snapshot, utc_now_iso


APP_VERSION = "1.0.0"
PRODUCT_NAME = "CAPI2 x402 Opportunity Radar"
FOUNDING_PRICE_EUR = 29
DEFAULT_PAYAI_DISCOVERY_URL = "https://facilitator.payai.network/discovery/resources?type=http&limit=1000"
DEFAULT_CDP_DISCOVERY_URL = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources?limit=1000&offset=0"


def _positive_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


CACHE_TTL_SECONDS = _positive_int_env("CACHE_TTL_SECONDS", 600, 60, 3600)
SOURCE_TIMEOUT_SECONDS = _positive_int_env("SOURCE_TIMEOUT_SECONDS", 12, 3, 30)

app = FastAPI(
    title=PRODUCT_NAME,
    version=APP_VERSION,
    description=(
        "Live x402 catalog analysis that ranks under-served API categories, benchmarks observable prices, "
        "and generates machine-readable launch briefs."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_CACHE_LOCK = asyncio.Lock()
_CACHE: dict[str, Any] = {"expires_at": 0.0, "intelligence": None}


class LaunchBriefRequest(BaseModel):
    category: str = Field(min_length=3, max_length=100)
    target_buyer: str | None = Field(default=None, max_length=300)
    max_build_days: int = Field(default=7, ge=1, le=30)


def _public_base_url(request: Request | None = None) -> str:
    configured = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    if request is not None:
        return str(request.base_url).rstrip("/")
    return ""


def _stripe_payment_link() -> str:
    return os.getenv("STRIPE_PAYMENT_LINK", "").strip()


def _access_key() -> str:
    return os.getenv("FOUNDING_ACCESS_KEY", "").strip()


def _fallback_items() -> list[dict[str, Any]]:
    # These deliberately use example.invalid and are never represented as live market data.
    return [
        {
            "_source": "fallback_example",
            "resource": "https://weather.example.invalid/v1/forecast",
            "type": "http",
            "method": "GET",
            "accepts": [{"network": "eip155:8453", "asset": "USDC", "amount": "5000"}],
            "metadata": {"serviceName": "Example Weather", "description": "Weather forecast data", "tags": ["weather"]},
        },
        {
            "_source": "fallback_example",
            "resource": "https://chain.example.invalid/v1/token",
            "type": "http",
            "method": "POST",
            "accepts": [{"network": "eip155:8453", "asset": "USDC", "amount": "20000"}],
            "metadata": {"serviceName": "Example Chain Data", "description": "Token and wallet information", "tags": ["onchain"]},
        },
        {
            "_source": "fallback_example",
            "resource": "https://docs.example.invalid/v1/pdf",
            "type": "http",
            "method": "POST",
            "accepts": [{"network": "eip155:8453", "asset": "USDC", "amount": "10000"}],
            "metadata": {"serviceName": "Example Document Parser", "description": "Extract text from PDF documents", "tags": ["pdf", "extract"]},
        },
        {
            "_source": "fallback_example",
            "resource": "https://news.example.invalid/v1/latest",
            "type": "http",
            "method": "GET",
            "accepts": [{"network": "eip155:8453", "asset": "USDC", "amount": "15000"}],
            "metadata": {"serviceName": "Example News", "description": "Current event headlines", "tags": ["news"]},
        },
    ]


def _source_definitions() -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = [
        {
            "name": "payai_bazaar",
            "url": os.getenv("PAYAI_DISCOVERY_URL", DEFAULT_PAYAI_DISCOVERY_URL).strip(),
            "headers": {},
        }
    ]
    cdp_token = os.getenv("CDP_BEARER_TOKEN", "").strip()
    if cdp_token:
        sources.append(
            {
                "name": "coinbase_cdp_bazaar",
                "url": os.getenv("CDP_DISCOVERY_URL", DEFAULT_CDP_DISCOVERY_URL).strip(),
                "headers": {"Authorization": f"Bearer {cdp_token}"},
            }
        )
    extras = [url.strip() for url in os.getenv("EXTRA_DISCOVERY_URLS", "").split(",") if url.strip()]
    for index, url in enumerate(extras, start=1):
        sources.append({"name": f"extra_{index}", "url": url, "headers": {}})
    return [source for source in sources if source["url"]]


async def _fetch_source(client: httpx.AsyncClient, source: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    started = time.perf_counter()
    status: dict[str, Any] = {
        "name": source["name"],
        "url": source["url"],
        "ok": False,
        "http_status": None,
        "items": 0,
        "latency_ms": None,
    }
    try:
        response = await client.get(source["url"], headers=source["headers"])
        status["http_status"] = response.status_code
        response.raise_for_status()
        payload = response.json()
        items = extract_items(payload)
        for item in items:
            item["_source"] = source["name"]
        status["ok"] = True
        status["items"] = len(items)
        return items, status
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        status["error"] = f"{exc.__class__.__name__}: {str(exc)[:180]}"
        return [], status
    finally:
        status["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)


async def _load_intelligence(*, force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    cached = _CACHE.get("intelligence")
    if not force and cached is not None and now < float(_CACHE.get("expires_at", 0)):
        return cached

    async with _CACHE_LOCK:
        now = time.monotonic()
        cached = _CACHE.get("intelligence")
        if not force and cached is not None and now < float(_CACHE.get("expires_at", 0)):
            return cached

        timeout = httpx.Timeout(SOURCE_TIMEOUT_SECONDS, connect=min(6, SOURCE_TIMEOUT_SECONDS))
        raw_items: list[dict[str, Any]] = []
        source_status: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": f"capi2-x402-opportunity-radar/{APP_VERSION}"},
        ) as client:
            results = await asyncio.gather(
                *(_fetch_source(client, source) for source in _source_definitions()),
                return_exceptions=True,
            )

        for result in results:
            if isinstance(result, Exception):
                source_status.append(
                    {
                        "name": "unknown",
                        "ok": False,
                        "items": 0,
                        "error": f"{result.__class__.__name__}: {str(result)[:180]}",
                    }
                )
                continue
            items, status = result
            raw_items.extend(items)
            source_status.append(status)

        data_mode = "live" if raw_items else "fallback_sample"
        if not raw_items:
            raw_items = _fallback_items()

        intelligence = build_intelligence(
            raw_items,
            source_status=source_status,
            data_mode=data_mode,
            captured_at=utc_now_iso(),
        )
        _CACHE["intelligence"] = intelligence
        _CACHE["expires_at"] = time.monotonic() + CACHE_TTL_SECONDS
        return intelligence


async def require_premium_access(request: Request) -> str:
    configured = _access_key()
    if not configured:
        raise HTTPException(status_code=503, detail="premium_access_not_configured")

    provided = request.headers.get("X-API-Key", "").strip()
    authorization = request.headers.get("Authorization", "").strip()
    if not provided and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if not provided:
        provided = request.query_params.get("api_key", "").strip()

    if not provided or not hmac.compare_digest(provided, configured):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "premium_access_required",
                "buy": "/buy",
                "price_eur": FOUNDING_PRICE_EUR,
                "header": "X-API-Key",
            },
            headers={"WWW-Authenticate": 'Bearer realm="capi2-radar"'},
        )
    return provided


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "capi2-x402-opportunity-radar",
        "version": APP_VERSION,
        "catalog_cache_ttl_seconds": CACHE_TTL_SECONDS,
        "premium_configured": bool(_access_key()),
        "checkout_configured": bool(_stripe_payment_link()),
        "sources_configured": [source["name"] for source in _source_definitions()],
    }


@app.get("/v1/snapshot")
async def snapshot() -> dict[str, Any]:
    intelligence = await _load_intelligence()
    return public_snapshot(intelligence)


@app.get("/v1/categories")
async def categories() -> dict[str, Any]:
    return {
        "protocol": "capi2.radar-categories/1.0",
        "categories": [
            {
                "slug": category["slug"],
                "label": category["label"],
                "build_difficulty": category["build_difficulty"],
            }
            for category in TAXONOMY
        ],
    }


@app.get("/v1/opportunities", dependencies=[Depends(require_premium_access)])
async def opportunities() -> dict[str, Any]:
    intelligence = await _load_intelligence()
    return {
        "protocol": intelligence["protocol"],
        "captured_at": intelligence["captured_at"],
        "data_mode": intelligence["data_mode"],
        "source_status": intelligence["source_status"],
        "methodology": intelligence["methodology"],
        "metrics": intelligence["metrics"],
        "opportunities": intelligence["opportunities"],
        "top_visible_resources": intelligence["top_visible_resources"],
    }


@app.get("/v1/catalog", dependencies=[Depends(require_premium_access)])
async def normalized_catalog() -> dict[str, Any]:
    intelligence = await _load_intelligence()
    return {
        "protocol": "capi2.normalized-x402-catalog/1.0",
        "captured_at": intelligence["captured_at"],
        "data_mode": intelligence["data_mode"],
        "count": len(intelligence["resources"]),
        "resources": intelligence["resources"],
    }


@app.post("/v1/launch-brief", dependencies=[Depends(require_premium_access)])
async def launch_brief(payload: LaunchBriefRequest) -> dict[str, Any]:
    intelligence = await _load_intelligence()
    try:
        return build_launch_brief(
            intelligence,
            category_slug=payload.category,
            target_buyer=payload.target_buyer,
            max_build_days=payload.max_build_days,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "category_not_found",
                "category": payload.category,
                "available": [category["slug"] for category in TAXONOMY],
            },
        ) from exc


@app.post("/v1/refresh", dependencies=[Depends(require_premium_access)])
async def refresh() -> dict[str, Any]:
    intelligence = await _load_intelligence(force=True)
    return {
        "ok": True,
        "captured_at": intelligence["captured_at"],
        "data_mode": intelligence["data_mode"],
        "resources_observed": intelligence["metrics"]["resources_observed"],
        "source_status": intelligence["source_status"],
    }


@app.get("/v1/quote")
async def quote(request: Request) -> dict[str, Any]:
    return {
        "protocol": "capi2.commercial-quote/1.0",
        "product": PRODUCT_NAME,
        "offer": "Founding Access",
        "price": {"amount": FOUNDING_PRICE_EUR, "currency": "EUR", "billing": "one_time"},
        "includes": [
            "full opportunity ranking",
            "normalized x402 catalog",
            "price benchmarks",
            "launch brief generator",
            "API access with X-API-Key",
        ],
        "checkout_url": f"{_public_base_url(request)}/buy",
        "checkout_ready": bool(_stripe_payment_link()),
        "delivery": "Access page immediately after successful Stripe Checkout",
        "limitations": "Market intelligence is heuristic and does not guarantee sales, revenue or endpoint availability.",
    }


@app.get("/buy")
async def buy():
    payment_link = _stripe_payment_link()
    if not payment_link:
        raise HTTPException(status_code=503, detail="checkout_not_configured")
    return RedirectResponse(payment_link, status_code=307)


@app.get("/access", response_class=HTMLResponse)
async def access_page(key: str = Query(default="", max_length=300)):
    configured = _access_key()
    valid = bool(configured and key and hmac.compare_digest(key, configured))
    if not valid:
        return HTMLResponse(
            """<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Access required</title><style>body{font-family:system-ui;background:#081019;color:#edf8f2;display:grid;place-items:center;min-height:100vh;margin:0}.box{max-width:620px;padding:40px;border:1px solid #28433d;border-radius:24px;background:#0d171d}a{color:#8fffc1}.button{display:inline-block;margin-top:18px;padding:13px 20px;border-radius:999px;background:#8fffc1;color:#06110b;text-decoration:none;font-weight:800}</style></head><body><main class='box'><h1>Premium access required</h1><p>This access link is missing or invalid. Complete the founding-access checkout to receive the premium API key.</p><a class='button' href='/buy'>Buy founding access — €29</a></main></body></html>""",
            status_code=401,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    safe_key = html.escape(key)
    js_key = json.dumps(key)
    page = f"""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width,initial-scale=1'>
  <meta name='robots' content='noindex,nofollow'>
  <title>Your CAPI2 Radar access</title>
  <style>
    :root{{--bg:#071018;--panel:#0d1921;--line:#24413d;--ink:#edfff5;--muted:#9bb8ad;--accent:#8fffc1;--accent2:#66d9ff}}
    *{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at 10% 0,#12362d 0,transparent 34%),var(--bg);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui;min-height:100vh}}
    main{{width:min(920px,92vw);margin:0 auto;padding:70px 0}} .badge{{display:inline-flex;padding:7px 12px;border:1px solid #39705f;border-radius:999px;color:var(--accent);font-size:13px}}
    h1{{font-size:clamp(36px,6vw,68px);line-height:1;margin:20px 0}} p{{color:var(--muted);line-height:1.7}} .panel{{background:rgba(13,25,33,.92);border:1px solid var(--line);border-radius:24px;padding:24px;margin:24px 0}}
    code,pre{{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}} .key{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:15px;background:#061017;border:1px solid #31534b;border-radius:14px;word-break:break-all}}
    button,a.button{{border:0;border-radius:999px;background:var(--accent);color:#06110b;padding:12px 18px;font-weight:800;cursor:pointer;text-decoration:none;display:inline-block}}
    pre{{overflow:auto;background:#050c11;border-radius:16px;padding:18px;color:#c9f6df;border:1px solid #1b332f;white-space:pre-wrap}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}}
  </style>
</head>
<body>
<main>
  <span class='badge'>PAYMENT RECEIVED · FOUNDING ACCESS</span>
  <h1>Your radar is unlocked.</h1>
  <p>The key below unlocks the full rankings, normalized catalog and launch-brief generator. It is also stored in this browser. Keep it private: this MVP uses one shared founding key and does not yet provide per-customer rotation.</p>
  <section class='panel'>
    <h2>API key</h2>
    <div class='key'><code id='key'>{safe_key}</code><button onclick='copyKey()'>Copy key</button></div>
  </section>
  <div class='grid'>
    <section class='panel'><h2>1. Get full ranking</h2><pre>curl -sS \\
  -H 'X-API-Key: YOUR_KEY' \\
  /v1/opportunities</pre></section>
    <section class='panel'><h2>2. Generate a launch brief</h2><pre>curl -sS -X POST \\
  -H 'Content-Type: application/json' \\
  -H 'X-API-Key: YOUR_KEY' \\
  -d '{{"category":"compliance_due_diligence"}}' \\
  /v1/launch-brief</pre></section>
  </div>
  <a class='button' href='/docs'>Open interactive API docs</a>
</main>
<script>
  const accessKey={js_key};
  localStorage.setItem('capi2RadarKey',accessKey);
  history.replaceState({{}},'', '/access');
  async function copyKey(){{await navigator.clipboard.writeText(accessKey);}}
</script>
</body></html>"""
    return HTMLResponse(
        page,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "Referrer-Policy": "no-referrer",
        },
    )


@app.get("/.well-known/agent.json")
async def agent_manifest(request: Request) -> dict[str, Any]:
    base = _public_base_url(request)
    return {
        "name": PRODUCT_NAME,
        "version": APP_VERSION,
        "protocol": "capi2.market-intel/1.0",
        "description": "Ranks under-served x402 API categories and generates launch-ready machine contracts.",
        "capabilities": [
            "x402 catalog normalization",
            "market gap ranking",
            "observable price benchmarking",
            "machine-readable API launch briefs",
        ],
        "endpoints": {
            "snapshot": {"method": "GET", "url": f"{base}/v1/snapshot", "access": "public"},
            "categories": {"method": "GET", "url": f"{base}/v1/categories", "access": "public"},
            "quote": {"method": "GET", "url": f"{base}/v1/quote", "access": "public"},
            "opportunities": {"method": "GET", "url": f"{base}/v1/opportunities", "access": "X-API-Key"},
            "catalog": {"method": "GET", "url": f"{base}/v1/catalog", "access": "X-API-Key"},
            "launch_brief": {"method": "POST", "url": f"{base}/v1/launch-brief", "access": "X-API-Key"},
        },
        "commercial_model": {
            "offer": "Founding Access",
            "price": {"amount": FOUNDING_PRICE_EUR, "currency": "EUR", "billing": "one_time"},
            "checkout": f"{base}/buy",
            "delivery": "Stripe redirects to an access page containing the API key",
        },
        "methodology_disclosure": "Opportunity scores are heuristics, not demand or revenue guarantees.",
    }


@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt(request: Request) -> str:
    base = _public_base_url(request)
    return f"""# {PRODUCT_NAME}

> Build what the x402 market is missing.

Public endpoints:
- GET {base}/v1/snapshot
- GET {base}/v1/categories
- GET {base}/v1/quote
- GET {base}/.well-known/agent.json

Premium endpoints (send `X-API-Key`):
- GET {base}/v1/opportunities
- GET {base}/v1/catalog
- POST {base}/v1/launch-brief
- POST {base}/v1/refresh

Commercial offer:
- Founding Access: EUR {FOUNDING_PRICE_EUR}, one time
- Checkout: {base}/buy

Important: opportunity scores combine catalog scarcity with disclosed assumptions and observable price/activity signals. They do not guarantee demand or revenue. Discovery catalogs can be stale, so verify seller endpoints before making decisions.
"""


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt() -> str:
    return "User-agent: *\nAllow: /\nDisallow: /access\n"


@app.get("/terms", response_class=HTMLResponse)
async def terms() -> str:
    return """<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Terms</title><style>body{max-width:760px;margin:50px auto;padding:0 20px;font:17px/1.7 system-ui;background:#071018;color:#eafff2}a{color:#8fffc1}</style></head><body><h1>Terms of use</h1><p>CAPI2 x402 Opportunity Radar is a digital market-intelligence service. Its rankings are heuristic and do not guarantee sales, income, investment returns or endpoint availability.</p><p>Third-party discovery catalogs may be incomplete, delayed or inaccurate. Buyers must independently verify technical, commercial and legal assumptions before acting.</p><p>Founding Access covers the current service and reasonable maintenance of this MVP. It does not promise every future feature or uninterrupted access. Refund and withdrawal requests are handled under applicable consumer law and the payment record.</p><p>The service must not be used to perform unlawful activity or to misrepresent analysis as regulated legal, medical or financial advice.</p><p><a href='/'>Return to product</a></p></body></html>"""


@app.get("/privacy", response_class=HTMLResponse)
async def privacy() -> str:
    return """<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Privacy</title><style>body{max-width:760px;margin:50px auto;padding:0 20px;font:17px/1.7 system-ui;background:#071018;color:#eafff2}a{color:#8fffc1}</style></head><body><h1>Privacy</h1><p>The application processes ordinary HTTP request data needed to operate and secure the service. The MVP does not create user profiles or intentionally store submitted launch-brief content.</p><p>Payments are processed by Stripe. Stripe receives the checkout and payment information needed to complete the purchase under its own privacy terms. Do not send passwords, private keys or sensitive personal data to the analysis endpoints.</p><p>Operational hosting and upstream catalog providers may log requests according to their own retention policies.</p><p><a href='/'>Return to product</a></p></body></html>"""


LANDING_PAGE = """<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'>
  <meta name='viewport' content='width=device-width,initial-scale=1'>
  <meta name='description' content='Live x402 market-gap rankings, price benchmarks and API launch briefs.'>
  <title>CAPI2 x402 Opportunity Radar</title>
  <style>
    :root{--bg:#061017;--panel:#0b1820;--panel2:#0f2027;--ink:#effff6;--muted:#9db9ae;--line:#23423b;--accent:#8fffc1;--cyan:#65dcff;--warn:#ffd28f}
    *{box-sizing:border-box} html{scroll-behavior:smooth} body{margin:0;background:radial-gradient(circle at 12% -8%,#15493b 0,transparent 31%),radial-gradient(circle at 92% 18%,#10324a 0,transparent 25%),var(--bg);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
    a{color:inherit} .wrap{width:min(1160px,92vw);margin:0 auto} nav{display:flex;align-items:center;justify-content:space-between;padding:24px 0}.brand{font-weight:900;letter-spacing:-.03em}.navlinks{display:flex;gap:18px;align-items:center}.navlinks a{text-decoration:none;color:var(--muted);font-size:14px}.pill{display:inline-flex;align-items:center;gap:8px;border:1px solid #36715e;border-radius:999px;padding:7px 12px;color:var(--accent);font-size:13px;background:#0a1c19}.dot{width:8px;height:8px;border-radius:50%;background:var(--accent);box-shadow:0 0 18px var(--accent)}
    header{padding:84px 0 58px}.eyebrow{color:var(--cyan);font-weight:800;letter-spacing:.12em;text-transform:uppercase;font-size:12px}.hero{display:grid;grid-template-columns:1.25fr .75fr;gap:52px;align-items:center}.hero h1{font-size:clamp(52px,8vw,104px);line-height:.91;letter-spacing:-.07em;margin:18px 0 24px}.hero h1 span{color:var(--accent)}.lead{max-width:720px;color:var(--muted);font-size:clamp(18px,2.3vw,24px);line-height:1.55}.actions{display:flex;gap:14px;flex-wrap:wrap;margin-top:32px}.button{display:inline-flex;align-items:center;justify-content:center;padding:15px 22px;border-radius:999px;text-decoration:none;font-weight:900;border:1px solid var(--accent);background:var(--accent);color:#04110a}.button.secondary{background:transparent;color:var(--ink);border-color:#365149}.pricebox{position:relative;background:linear-gradient(150deg,rgba(15,36,39,.96),rgba(7,19,26,.96));border:1px solid #31574d;border-radius:28px;padding:30px;box-shadow:0 24px 80px rgba(0,0,0,.28)}.pricebox:before{content:'FOUNDING OFFER';position:absolute;top:-13px;right:24px;background:var(--warn);color:#2b1a00;padding:6px 11px;border-radius:999px;font-size:11px;font-weight:900;letter-spacing:.08em}.price{font-size:70px;line-height:1;font-weight:950;letter-spacing:-.06em;margin:14px 0}.price small{font-size:16px;color:var(--muted);letter-spacing:0}.checks{list-style:none;padding:0;margin:24px 0}.checks li{margin:12px 0;color:#cce7dc}.checks li:before{content:'✓';color:var(--accent);font-weight:900;margin-right:10px}
    section{padding:70px 0}.sectionhead{display:flex;justify-content:space-between;gap:30px;align-items:end;margin-bottom:24px}.sectionhead h2{font-size:clamp(34px,5vw,60px);letter-spacing:-.055em;line-height:1;margin:0}.sectionhead p{max-width:540px;color:var(--muted);line-height:1.6}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.metric,.card{border:1px solid var(--line);background:rgba(11,24,32,.88);border-radius:20px;padding:22px}.metric strong{display:block;font-size:34px;letter-spacing:-.04em}.metric span{color:var(--muted);font-size:13px}.opportunities{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.card .rank{color:var(--cyan);font-size:12px;font-weight:900;letter-spacing:.12em}.card h3{font-size:24px;margin:10px 0}.score{font-size:46px;font-weight:950;color:var(--accent);letter-spacing:-.05em}.meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:15px}.chip{font-size:12px;border:1px solid #304b45;border-radius:999px;padding:6px 9px;color:#b9d2c8}.how{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.step{padding:26px;border-top:1px solid #3b675a}.step b{color:var(--accent);font-size:13px}.step h3{font-size:25px;margin:12px 0}.step p{color:var(--muted);line-height:1.65}.code{background:#040b10;border:1px solid #1e3632;border-radius:22px;padding:24px;overflow:auto;color:#c8f9df;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;line-height:1.65;white-space:pre-wrap}.notice{border-left:3px solid var(--warn);padding:14px 18px;background:#241d10;color:#ffe7be;border-radius:0 14px 14px 0}.status{color:var(--muted);font-size:13px;margin-top:14px}footer{border-top:1px solid var(--line);padding:35px 0 55px;color:var(--muted);display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}footer a{color:var(--muted)}
    @media(max-width:880px){.hero{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}.opportunities,.how{grid-template-columns:1fr}.navlinks a:not(.button){display:none}}@media(max-width:520px){.metrics{grid-template-columns:1fr}.hero h1{font-size:54px}.price{font-size:58px}}
  </style>
</head>
<body>
<div class='wrap'>
  <nav><div class='brand'>CAPI2 / RADAR</div><div class='navlinks'><a href='#evidence'>Evidence</a><a href='/docs'>API</a><a class='button' href='/buy'>Buy access</a></div></nav>
  <header>
    <div class='hero'>
      <div>
        <span class='pill'><i class='dot'></i> LIVE X402 CATALOG SIGNAL</span>
        <div class='eyebrow' style='margin-top:28px'>Market intelligence for agent commerce</div>
        <h1>Build what the market is <span>missing.</span></h1>
        <p class='lead'>The Bazaar tells you what is already for sale. CAPI2 ranks the under-served API categories, benchmarks visible prices and turns the best gap into a launch-ready machine contract.</p>
        <div class='actions'><a class='button' href='/buy'>Get Founding Access — €29</a><a class='button secondary' href='#evidence'>See the live preview</a></div>
        <div class='status' id='sourceStatus'>Loading catalog evidence…</div>
      </div>
      <aside class='pricebox'>
        <div style='color:var(--muted);font-weight:800'>Lifetime MVP access</div>
        <div class='price'>€29 <small>one time</small></div>
        <ul class='checks'><li>Full ranked opportunity list</li><li>Normalized x402 catalog</li><li>Observable price benchmarks</li><li>Machine-readable launch briefs</li><li>Agent-ready API key</li></ul>
        <a class='button' style='width:100%' href='/buy'>Unlock the radar</a>
      </aside>
    </div>
  </header>

  <section id='evidence'>
    <div class='sectionhead'><h2>Current market<br>snapshot.</h2><p>The free layer exposes the evidence base and top three scores. Premium access unlocks every category, examples, benchmarks and the launch-brief generator.</p></div>
    <div class='metrics'>
      <div class='metric'><strong id='resourceCount'>—</strong><span>resources observed</span></div>
      <div class='metric'><strong id='pricedCount'>—</strong><span>parseable prices</span></div>
      <div class='metric'><strong id='medianPrice'>—</strong><span>median visible price</span></div>
      <div class='metric'><strong id='dataMode'>—</strong><span>data mode</span></div>
    </div>
    <div class='opportunities' id='opportunities' style='margin-top:16px'></div>
  </section>

  <section>
    <div class='sectionhead'><h2>From catalog<br>to product.</h2><p>It is not another directory. The paid output is a decision package an agent or developer can execute.</p></div>
    <div class='how'>
      <div class='step'><b>01 · OBSERVE</b><h3>Normalize supply</h3><p>Merge discovery listings, payment terms, networks, descriptions and visible activity into one comparable catalog.</p></div>
      <div class='step'><b>02 · SCORE</b><h3>Expose the assumptions</h3><p>Rank gaps using scarcity, a disclosed demand prior, observable pricing and activity. No hidden “AI magic” or invented demand.</p></div>
      <div class='step'><b>03 · SHIP</b><h3>Generate the contract</h3><p>Receive endpoints, request and response examples, x402 declaration, launch price, sales copy, validation gates and a seven-day build plan.</p></div>
    </div>
  </section>

  <section>
    <div class='sectionhead'><h2>Machine-readable<br>by default.</h2><p>Use the same resource from a browser, script or autonomous agent.</p></div>
    <div class='code'>curl -sS -X POST \\
  -H 'Content-Type: application/json' \\
  -H 'X-API-Key: YOUR_KEY' \\
  -d '{"category":"ai_evaluation","max_build_days":7}' \\
  https://capi2-x402-opportunity-radar.onrender.com/v1/launch-brief</div>
  </section>

  <section><div class='notice'><strong>Honest limitation:</strong> a high opportunity score is not proof that buyers will pay. Discovery catalogs can also be stale. The product makes those assumptions visible and includes validation gates before serious investment.</div></section>

  <footer><span>© CAPI2 x402 Opportunity Radar</span><span><a href='/terms'>Terms</a> · <a href='/privacy'>Privacy</a> · <a href='/.well-known/agent.json'>Agent manifest</a> · <a href='/llms.txt'>llms.txt</a></span></footer>
</div>
<script>
  const euro = n => n == null ? '—' : '$' + Number(n).toFixed(Number(n) < .01 ? 4 : 3).replace(/0+$/,'').replace(/\.$/,'');
  fetch('/v1/snapshot').then(r=>r.json()).then(data=>{
    const m=data.metrics||{};
    document.getElementById('resourceCount').textContent=m.resources_observed ?? '—';
    document.getElementById('pricedCount').textContent=m.resources_with_parseable_price ?? '—';
    document.getElementById('medianPrice').textContent=euro(m.median_price_usd);
    document.getElementById('dataMode').textContent=(data.data_mode||'unknown').replace('_',' ');
    const statuses=(data.source_status||[]).map(s=>`${s.name}: ${s.ok?'live':'unavailable'} (${s.items||0})`).join(' · ');
    document.getElementById('sourceStatus').textContent=`Captured ${new Date(data.captured_at).toLocaleString()} · ${statuses || 'fallback only'}`;
    const root=document.getElementById('opportunities');
    root.innerHTML=(data.opportunity_preview||[]).map(o=>`<article class='card'><div class='rank'>RANK ${o.rank}</div><h3>${o.category_label}</h3><div class='score'>${o.opportunity_score}</div><div style='color:var(--muted)'>heuristic opportunity score</div><div class='meta'><span class='chip'>${o.resources_observed} observed</span><span class='chip'>launch price ${euro(o.suggested_x402_price_usd)}</span><span class='chip'>${o.confidence} confidence</span></div></article>`).join('');
  }).catch(err=>{document.getElementById('sourceStatus').textContent='The live preview is temporarily unavailable; checkout and API docs remain available.';});
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
async def landing_page() -> HTMLResponse:
    return HTMLResponse(LANDING_PAGE, headers={"Cache-Control": "public, max-age=300"})
