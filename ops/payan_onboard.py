import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

BASE = "https://payanagent.com"
WALLET = "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a"
DEMAND_ORIGIN = "https://capi2-demand-tools.onrender.com"
CLAIM_ORIGIN = "https://capi2-claim-verify.onrender.com"
PORT = int(os.getenv("PORT", "10000"))

OFFERS = [
    ("capi2 · SHA-256 Hash", "Low-latency SHA-256 digest for UTF-8 text. Deterministic x402 microtool for integrity, cache keys and deduplication.", "Developer Tools", ["sha256", "hash", "digest", "x402", "agent-tools"], f"{DEMAND_ORIGIN}/v1/hash/sha256", {"text": "hello"}),
    ("capi2 · SHA-512 Hash", "Low-latency SHA-512 digest for UTF-8 text. Deterministic x402 microtool for integrity workflows.", "Developer Tools", ["sha512", "hash", "digest", "x402", "agent-tools"], f"{DEMAND_ORIGIN}/v1/hash/sha512", {"text": "hello"}),
    ("capi2 · Base64 Encode", "Encode UTF-8 text to Base64 for API payloads and agent interoperability.", "Developer Tools", ["base64", "encode", "encoding", "x402", "agent-tools"], f"{DEMAND_ORIGIN}/v1/base64/encode", {"text": "hello"}),
    ("capi2 · Base64 Decode", "Decode Base64 into UTF-8 text for deterministic agent workflows.", "Developer Tools", ["base64", "decode", "encoding", "x402", "agent-tools"], f"{DEMAND_ORIGIN}/v1/base64/decode", {"data": "aGVsbG8=", "urlsafe": False}),
    ("capi2 · JWT Decode", "Decode JWT header and payload without signature verification for token inspection and debugging.", "Developer Tools", ["jwt", "decode", "token", "x402", "agent-tools"], f"{DEMAND_ORIGIN}/v1/jwt/decode", {"token": "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJ0ZXN0In0."}),
    ("capi2 · JSON Canonicalize + SHA-256", "Canonicalize JSON with sorted keys and compact separators and return a SHA-256 fingerprint.", "Developer Tools", ["json", "canonicalize", "sha256", "x402", "agent-tools"], f"{DEMAND_ORIGIN}/v1/json/canonicalize", {"value": {"b": 2, "a": 1}}),
    ("capi2 · Public Claim Verification", "Verify one public vendor claim against a supplied public source URL and return evidence with a machine-readable verdict.", "Research", ["verification", "evidence", "research", "x402", "agent-tools"], f"{CLAIM_ORIGIN}/v1/claim-verify", {"vendor_url": "https://example.com", "claim": "Example Domain"}),
]

state = {"ok": False, "status": "starting", "agentId": None, "apiKeyPrefix": None, "offers": [], "errors": []}


def get_existing_titles():
    try:
        r = requests.get(f"{BASE}/api/v1/offers", params={"q": "capi2", "offerType": "api", "limit": 100}, timeout=20)
        r.raise_for_status()
        body = r.json()
        rows = body.get("offers", []) if isinstance(body, dict) else body
        return {str(x.get("title", "")): x for x in rows if isinstance(x, dict)}
    except Exception as exc:
        state["errors"].append(f"catalog:{exc.__class__.__name__}")
        return {}


def onboard():
    time.sleep(3)
    wanted = {row[0] for row in OFFERS}
    existing = get_existing_titles()
    if wanted.issubset(set(existing)):
        state["offers"] = [
            {"title": t, "offerId": existing[t].get("offerId") or existing[t].get("id"), "buyUrl": existing[t].get("buyUrl")}
            for t in sorted(wanted)
        ]
        state.update(ok=True, status="already_listed")
        print(f"payanagent onboarding: already_listed offers={len(state['offers'])}", flush=True)
        return

    payload = {
        "name": "capi2 Agent Commerce",
        "description": "x402-native micro-APIs for public verification, hashing, encoding and structured utility workflows.",
        "walletAddress": WALLET,
        "chain": "base",
        "tags": ["x402", "verification", "hashing", "encoding", "agent-tools"],
        "providerType": "api",
        "agentUrl": DEMAND_ORIGIN,
    }
    try:
        r = requests.post(f"{BASE}/api/v1/agents", json=payload, timeout=25)
        if not r.ok:
            state["status"] = "registration_failed"
            state["errors"].append(f"agent:{r.status_code}:{r.text[:300]}")
            print(f"payanagent onboarding: registration_failed status={r.status_code} error={r.text[:300]}", flush=True)
            return
        reg = r.json()
        api_key = reg.get("apiKey")
        state["agentId"] = reg.get("agentId")
        state["apiKeyPrefix"] = reg.get("apiKeyPrefix")
        if not api_key:
            state["status"] = "registration_failed"
            state["errors"].append("agent:no_api_key")
            return

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        created = []
        for title, description, category, tags, url, verification_body in OFFERS:
            if title in existing:
                row = existing[title]
                created.append({"title": title, "offerId": row.get("offerId") or row.get("id"), "buyUrl": row.get("buyUrl"), "status": "existing"})
                continue
            body = {
                "title": title,
                "description": description,
                "category": category,
                "tags": tags,
                "offerType": "api",
                "externalUrl": url,
                "httpMethod": "POST",
                "verificationBody": verification_body,
            }
            rr = requests.post(f"{BASE}/api/v1/offers", headers=headers, json=body, timeout=35)
            if rr.ok:
                data = rr.json()
                offer_id = data.get("offerId") or data.get("id")
                created.append({"title": title, "offerId": offer_id, "buyUrl": data.get("buyUrl"), "status": "created"})
                print(f"payanagent offer: status={rr.status_code} title={title} offerId={offer_id}", flush=True)
            else:
                err = rr.text[:240].replace("\n", " ")
                state["errors"].append(f"offer:{title}:{rr.status_code}:{err}")
                print(f"payanagent offer: failed status={rr.status_code} title={title} error={err}", flush=True)

        state["offers"] = created
        state["ok"] = len(created) == len(OFFERS)
        state["status"] = "listed" if state["ok"] else "partial"
        print(f"payanagent onboarding: status={state['status']} agentId={state['agentId']} offers={len(created)}/{len(OFFERS)}", flush=True)
        api_key = None
    except Exception as exc:
        state["status"] = "exception"
        state["errors"].append(f"onboard:{exc.__class__.__name__}:{str(exc)[:240]}")
        print(f"payanagent onboarding: exception={exc.__class__.__name__} detail={str(exc)[:240]}", flush=True)


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
    threading.Thread(target=onboard, daemon=True).start()
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
