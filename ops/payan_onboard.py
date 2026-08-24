import base64
import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

BASE = "https://payanagent.com"
CATALOG_HEALTH_REPOSITORY = "https://github.com/vandurmedries/genesis-forge-autonomous-earner"
CATALOG_HEALTH_SCRIPT = f"{CATALOG_HEALTH_REPOSITORY}/blob/codex/capi2-buyer-seller-fix/tools/payan_catalog_health.mjs"
CATALOG_HEALTH_SAMPLE = f"{CATALOG_HEALTH_REPOSITORY}/blob/codex/capi2-buyer-seller-fix/reports/payan-catalog-health-sample.json"
WALLET = "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a"
PORT = int(os.getenv("PORT", "10000"))
SCAN_SECONDS = int(os.getenv("CAPI2_REQUEST_SCAN_SECONDS", "60"))
MAX_BIDS_PER_DAY = int(os.getenv("CAPI2_MAX_BIDS_PER_DAY", "5"))
PROVIDER_API_KEY = os.getenv("PAYANAGENT_API_KEY")
PROVIDER_AGENT_ID = os.getenv("PAYANAGENT_AGENT_ID")
ALLOW_PROVIDER_REGISTRATION = os.getenv("CAPI2_ALLOW_PROVIDER_REGISTRATION", "false").lower() == "true"
LEGACY_PROVIDER_AGENT_IDS = {
    value.strip()
    for value in os.getenv(
        "CAPI2_LEGACY_PROVIDER_AGENT_IDS",
        "j5722ms4nx6zy2e6mkmcm5xqrn8d2jtc,j57a4azbt4e2620g6mj0mhdnfd8d3e0w",
    ).split(",")
    if value.strip()
}

COORDINATION_ONLY_PHRASES = (
    "coordination only",
    "collaborator discovery only",
    "separately funded",
    "no bid is automatically accepted",
    "not paid through payan",
    "will carry the reward",
    "external bounty",
)

state = {
    "ok": False,
    "status": "starting",
    "agentId": None,
    "apiKeyPrefix": None,
    "lastScanAt": None,
    "openRequestsScanned": 0,
    "matchingRequests": [],
    "bids": [],
    "fulfilled": [],
    "errors": [],
}

api_key = PROVIDER_API_KEY
bid_request_ids = set()
fulfilled_request_ids = set()
bid_day = None
bids_today = 0


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def auth_headers():
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def register_provider():
    global api_key
    if api_key and PROVIDER_AGENT_ID:
        state["agentId"] = PROVIDER_AGENT_ID
        state["apiKeyPrefix"] = "configured"
        print(f"payan buyer-watch: using configured provider agentId={state['agentId']}", flush=True)
        return
    if not ALLOW_PROVIDER_REGISTRATION:
        raise RuntimeError(
            "provider_identity_missing:set PAYANAGENT_API_KEY and PAYANAGENT_AGENT_ID; "
            "automatic registration is disabled to prevent duplicate sellers"
        )
    payload = {
        "name": "capi2 Deterministic Utility Provider",
        "description": "Automated provider for deterministic SHA-256/SHA-512 hashing, Base64 encode/decode, JWT payload decoding, and canonical JSON fingerprints. Bids only when the request clearly matches one of these capabilities.",
        "walletAddress": WALLET,
        "chain": "base",
        "tags": ["sha256", "sha512", "base64", "jwt", "json", "deterministic", "x402"],
        "providerType": "agent",
        "agentUrl": "https://capi2-demand-tools.onrender.com",
    }
    r = requests.post(f"{BASE}/api/v1/agents", json=payload, timeout=25)
    if not r.ok:
        raise RuntimeError(f"register_provider:{r.status_code}:{r.text[:240]}")
    body = r.json()
    api_key = body.get("apiKey")
    if not api_key:
        raise RuntimeError("register_provider:no_api_key")
    state["agentId"] = body.get("agentId")
    state["apiKeyPrefix"] = body.get("apiKeyPrefix")
    print(f"payan buyer-watch: provider registered agentId={state['agentId']}", flush=True)


def detect_capability(title, description):
    title_text = title.lower().strip()
    description_text = description.lower().strip()
    text = f"{title_text} {description_text}"
    # Skip obviously unrelated/risky requests even if a keyword collides.
    blocked = ("exploit", "malware", "steal", "password", "credential theft", "bypass auth")
    if any(x in text for x in blocked):
        return None
    if any(x in text for x in COORDINATION_ONLY_PHRASES):
        return None

    if "catalog endpoint-health checker" in title_text or (
        "catalog" in title_text and "health checker" in title_text
    ):
        return "catalog_health"

    # Require the requested operation in the title. Descriptions often contain
    # incidental hashes, benchmarks, or examples that are not the deliverable.
    if ("canonical" in title_text or "canonicalize" in title_text) and "json" in title_text:
        return "json_canonicalize"
    if "base64" in title_text and any(x in title_text for x in ("decode", "decoding")):
        return "base64_decode"
    if "base64" in title_text and any(x in title_text for x in ("encode", "encoding")):
        return "base64_encode"
    if "jwt" in title_text and any(x in title_text for x in ("decode", "inspect", "payload", "header")):
        return "jwt_decode"
    if "sha512" in title_text or "sha-512" in title_text:
        return "sha512"
    if "sha256" in title_text or "sha-256" in title_text:
        return "sha256"
    return None


def has_solvable_input(req, capability):
    if capability == "catalog_health":
        return True
    payload = parse_payload(req.get("inputPayload"))
    if payload is None:
        return False
    try:
        solve(capability, payload)
        return True
    except (ValueError, TypeError, json.JSONDecodeError, base64.binascii.Error):
        return False


def already_bid_remotely(request_id):
    r = requests.get(f"{BASE}/api/v1/requests/{request_id}", timeout=20)
    if not r.ok:
        raise RuntimeError(f"request_detail:{r.status_code}:{r.text[:180]}")
    bids = r.json().get("bids", [])
    for bid in bids:
        bidder_id = bid.get("bidderId")
        if str(bidder_id) == str(state.get("agentId")) or str(bidder_id) in LEGACY_PROVIDER_AGENT_IDS:
            return True
    return False


def bid_message(capability):
    labels = {
        "sha256": "SHA-256 hashing",
        "sha512": "SHA-512 hashing",
        "base64_encode": "Base64 encoding",
        "base64_decode": "Base64 decoding",
        "jwt_decode": "JWT header/payload decoding without signature verification",
        "json_canonicalize": "canonical JSON + SHA-256 fingerprinting",
        "catalog_health": "a no-payment endpoint health report for the top PayanAgent catalog offers",
    }
    return (
        f"capi2 can deliver this automatically as deterministic {labels[capability]}. "
        "No model guesswork; machine-readable JSON output. Bid is 1 cent USDC and delivery is automated after acceptance."
    )


def reset_bid_budget():
    global bid_day, bids_today
    day = datetime.now(timezone.utc).date().isoformat()
    if day != bid_day:
        bid_day = day
        bids_today = 0


def submit_bid(req, capability):
    global bids_today
    reset_bid_budget()
    if bids_today >= MAX_BIDS_PER_DAY:
        return False
    request_id = req.get("_id") or req.get("id")
    if not request_id or request_id in bid_request_ids:
        return False
    if already_bid_remotely(request_id):
        bid_request_ids.add(request_id)
        # Preserve capability mapping across deploys so an accepted remote bid
        # is still fulfilled automatically after this process restarts.
        state["bids"].append({
            "requestId": request_id,
            "bidId": None,
            "capability": capability,
            "priceCents": 1,
            "at": now_iso(),
            "status": "existing_remote_bid",
        })
        state["bids"] = state["bids"][-20:]
        return False
    budget = int(req.get("budgetMaxCents") or 0)
    if budget < 1:
        return False
    body = {
        "priceCents": 1,
        "estimatedDurationSeconds": 60,
        "message": bid_message(capability),
    }
    r = requests.post(
        f"{BASE}/api/v1/requests/{request_id}/bid",
        headers=auth_headers(),
        json=body,
        timeout=20,
    )
    if r.status_code == 201:
        bid_id = r.json().get("bidId")
        bid_request_ids.add(request_id)
        bids_today += 1
        row = {"requestId": request_id, "bidId": bid_id, "capability": capability, "priceCents": 1, "at": now_iso()}
        state["bids"].append(row)
        state["bids"] = state["bids"][-20:]
        print(f"payan buyer-watch: BID request={request_id} capability={capability} bidId={bid_id} price=1c", flush=True)
        return True
    # A duplicate/closed request is not fatal; retain a bounded diagnostic.
    print(f"payan buyer-watch: bid rejected request={request_id} status={r.status_code} body={r.text[:180]}", flush=True)
    return False


def parse_payload(raw):
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw
    s = raw.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


def get_text_value(payload, *keys):
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            if key in payload and isinstance(payload[key], str):
                return payload[key]
    return None


def solve(capability, payload):
    if capability == "catalog_health":
        result = run_catalog_health_check()
        result.update({
            "repository": CATALOG_HEALTH_REPOSITORY,
            "nodeScript": CATALOG_HEALTH_SCRIPT,
            "sampleReport": CATALOG_HEALTH_SAMPLE,
            "run": "node tools/payan_catalog_health.mjs > report.json 2> summary.md",
            "probePolicy": "Unpaid OPTIONS requests only; 402 is classified alive.",
        })
        return result
    if capability == "sha256":
        text = get_text_value(payload, "text", "input", "value", "data")
        if text is None:
            raise ValueError("missing text input")
        return {"algorithm": "sha256", "digest": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    if capability == "sha512":
        text = get_text_value(payload, "text", "input", "value", "data")
        if text is None:
            raise ValueError("missing text input")
        return {"algorithm": "sha512", "digest": hashlib.sha512(text.encode("utf-8")).hexdigest()}
    if capability == "base64_encode":
        text = get_text_value(payload, "text", "input", "value", "data")
        if text is None:
            raise ValueError("missing text input")
        return {"encoding": "base64", "encoded": base64.b64encode(text.encode("utf-8")).decode("ascii")}
    if capability == "base64_decode":
        data = get_text_value(payload, "data", "text", "input", "value")
        if data is None:
            raise ValueError("missing base64 input")
        decoded = base64.b64decode(data, validate=True).decode("utf-8")
        return {"encoding": "base64", "decoded": decoded}
    if capability == "jwt_decode":
        token = get_text_value(payload, "token", "jwt", "text", "input")
        if token is None:
            raise ValueError("missing JWT token")
        parts = token.split(".")
        if len(parts) < 2:
            raise ValueError("invalid JWT shape")
        def dec(part):
            pad = "=" * ((4 - len(part) % 4) % 4)
            return json.loads(base64.urlsafe_b64decode(part + pad).decode("utf-8"))
        return {"verified": False, "header": dec(parts[0]), "payload": dec(parts[1]), "note": "Decoded only; signature not verified."}
    if capability == "json_canonicalize":
        value = payload.get("value") if isinstance(payload, dict) and "value" in payload else payload
        if isinstance(value, str):
            value = json.loads(value)
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {"canonical": canonical, "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
    raise ValueError("unsupported capability")


def run_catalog_health_check(limit=100):
    offers = []
    cursor = None
    while len(offers) < limit:
        params = {"sort": "top", "limit": min(100, limit - len(offers))}
        if cursor:
            params["cursor"] = cursor
        response = requests.get(f"{BASE}/api/v1/offers", params=params, timeout=20)
        response.raise_for_status()
        page = response.json()
        rows = page.get("offers", [])
        offers.extend(rows)
        cursor = page.get("nextCursor")
        if not cursor or not rows:
            break

    def probe(offer):
        offer_id = offer.get("_id") or offer.get("id")
        endpoint = offer.get("buyUrl") or (f"/x402/{offer_id}" if offer_id else None)
        url = endpoint if str(endpoint).startswith("http") else f"{BASE}{endpoint}"
        started = time.monotonic()
        try:
            response = requests.options(url, timeout=5, allow_redirects=True)
            elapsed = round((time.monotonic() - started) * 1000)
            code = response.status_code
            status = "alive" if code < 500 else "5xx"
            if code == 408:
                status = "timeout"
            elif 400 <= code < 500 and code != 402:
                status = "4xx"
            return {"offerId": offer_id, "title": offer.get("title"), "endpoint": url, "status": status, "httpCode": code, "latencyMs": elapsed}
        except requests.Timeout:
            return {"offerId": offer_id, "title": offer.get("title"), "endpoint": url, "status": "timeout", "httpCode": None, "latencyMs": round((time.monotonic() - started) * 1000)}
        except requests.RequestException:
            return {"offerId": offer_id, "title": offer.get("title"), "endpoint": url, "status": "dead", "httpCode": None, "latencyMs": round((time.monotonic() - started) * 1000)}

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(probe, offers[:limit]))
    counts = {name: sum(1 for row in results if row["status"] == name) for name in ("alive", "dead", "timeout", "4xx", "5xx")}
    return {
        "generatedAt": now_iso(),
        "offersChecked": len(results),
        "counts": counts,
        "summaryMarkdown": f"Checked {len(results)} offers: {counts['alive']} alive; {len(results) - counts['alive']} require review.",
        "results": results,
    }


def maybe_fulfill(request_id, capability):
    if request_id in fulfilled_request_ids:
        return
    r = requests.get(f"{BASE}/api/v1/requests/{request_id}", headers=auth_headers(), timeout=20)
    if not r.ok:
        return
    detail = r.json()
    req = detail.get("request") or {}
    status = req.get("status")
    provider_id = req.get("providerId")
    if status == "accepted" and str(provider_id) == str(state.get("agentId")):
        payload = parse_payload(req.get("inputPayload"))
        try:
            output = solve(capability, payload)
        except Exception as exc:
            state["errors"].append(f"solve:{request_id}:{exc}")
            state["errors"] = state["errors"][-20:]
            print(f"payan buyer-watch: accepted but cannot solve request={request_id} error={exc}", flush=True)
            return
        body = {"outputPayload": json.dumps({"protocol": "capi2.request-delivery/1.0", "capability": capability, "result": output}, separators=(",", ":"))}
        rr = requests.post(f"{BASE}/api/v1/requests/{request_id}/fulfill", headers=auth_headers(), json=body, timeout=20)
        if rr.ok:
            fulfilled_request_ids.add(request_id)
            row = {"requestId": request_id, "capability": capability, "at": now_iso()}
            state["fulfilled"].append(row)
            state["fulfilled"] = state["fulfilled"][-20:]
            print(f"payan buyer-watch: FULFILLED request={request_id} capability={capability}", flush=True)
        else:
            print(f"payan buyer-watch: fulfill rejected request={request_id} status={rr.status_code} body={rr.text[:180]}", flush=True)


def scan_once():
    r = requests.get(f"{BASE}/api/v1/requests", params={"status": "open", "limit": 100}, timeout=20)
    if not r.ok:
        raise RuntimeError(f"request_scan:{r.status_code}:{r.text[:200]}")
    rows = r.json().get("requests", [])
    state["lastScanAt"] = now_iso()
    state["openRequestsScanned"] = len(rows)
    matches = []
    for req in rows:
        title = str(req.get("title") or "")
        description = str(req.get("description") or "")
        capability = detect_capability(title, description)
        if not capability:
            continue
        if not has_solvable_input(req, capability):
            continue
        request_id = req.get("_id") or req.get("id")
        matches.append({"requestId": request_id, "title": title[:160], "capability": capability, "budgetMaxCents": req.get("budgetMaxCents")})
        submit_bid(req, capability)
    state["matchingRequests"] = matches[:20]
    # Poll requests we've already bid on; if accepted by the buyer, deliver automatically.
    capability_by_request = {x["requestId"]: x["capability"] for x in state["bids"]}
    for request_id in list(bid_request_ids):
        capability = capability_by_request.get(request_id)
        if capability:
            maybe_fulfill(request_id, capability)
    print(f"payan buyer-watch: scan open={len(rows)} matches={len(matches)} bidsToday={bids_today}", flush=True)


def worker():
    try:
        register_provider()
        state["ok"] = True
        state["status"] = "watching_open_requests"
    except Exception as exc:
        state["status"] = "registration_failed"
        state["errors"].append(str(exc)[:300])
        print(f"payan buyer-watch: registration failed {exc}", flush=True)
        return
    while True:
        try:
            scan_once()
        except Exception as exc:
            state["errors"].append(f"scan:{exc.__class__.__name__}:{str(exc)[:220]}")
            state["errors"] = state["errors"][-20:]
            print(f"payan buyer-watch: scan error={exc.__class__.__name__} detail={str(exc)[:200]}", flush=True)
        time.sleep(max(60, SCAN_SECONDS))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(state, separators=(",", ":")).encode()
        self.send_response(200 if state.get("ok") else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
