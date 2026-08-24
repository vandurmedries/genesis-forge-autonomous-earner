import base64
import hashlib
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

BASE = "https://payanagent.com"
PORT = int(os.getenv("PORT", "10000"))
PUBLIC_ORIGIN = os.getenv("CAPI2_PUBLIC_ORIGIN", "https://capi2-payan-native.onrender.com").rstrip("/")
RELAY_TOKEN = os.environ["CAPI2_NATIVE_RELAY_TOKEN"]
WALLET = "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a"
SELLER_API_KEY = os.getenv("PAYANAGENT_NATIVE_API_KEY")
SELLER_AGENT_ID = os.getenv("PAYANAGENT_NATIVE_AGENT_ID")
ALLOW_SELLER_REGISTRATION = os.getenv("CAPI2_ALLOW_SELLER_REGISTRATION", "false").lower() == "true"

OFFERS = [
    {
        "slug": "sha256",
        "title": "capi2 Native · SHA-256 Hash",
        "description": "Deterministic SHA-256 digest of UTF-8 text. Immediate JSON output for integrity checks, cache keys and deduplication.",
        "category": "Developer Tools",
        "tags": ["sha256", "hash", "digest", "developer-tools", "agent-tools"],
        "inputSchema": '{"text":"<UTF-8 text>"}',
        "outputSchema": '{"algorithm":"sha256","digest":"<64 hex chars>"}',
    },
    {
        "slug": "sha512",
        "title": "capi2 Native · SHA-512 Hash",
        "description": "Deterministic SHA-512 digest of UTF-8 text with immediate machine-readable JSON output.",
        "category": "Developer Tools",
        "tags": ["sha512", "hash", "digest", "developer-tools", "agent-tools"],
        "inputSchema": '{"text":"<UTF-8 text>"}',
        "outputSchema": '{"algorithm":"sha512","digest":"<128 hex chars>"}',
    },
    {
        "slug": "base64-encode",
        "title": "capi2 Native · Base64 Encode",
        "description": "Encode UTF-8 text to standard Base64 for API payloads and agent interoperability.",
        "category": "Developer Tools",
        "tags": ["base64", "encode", "encoding", "developer-tools", "agent-tools"],
        "inputSchema": '{"text":"<UTF-8 text>"}',
        "outputSchema": '{"encoding":"base64","encoded":"..."}',
    },
    {
        "slug": "base64-decode",
        "title": "capi2 Native · Base64 Decode",
        "description": "Decode standard Base64 to UTF-8 text with strict validation and deterministic JSON output.",
        "category": "Developer Tools",
        "tags": ["base64", "decode", "encoding", "developer-tools", "agent-tools"],
        "inputSchema": '{"data":"<base64 string>"}',
        "outputSchema": '{"encoding":"base64","decoded":"..."}',
    },
    {
        "slug": "jwt-decode",
        "title": "capi2 Native · JWT Decode",
        "description": "Decode JWT header and payload without signature verification. Intended for token inspection and debugging, not authentication decisions.",
        "category": "Developer Tools",
        "tags": ["jwt", "decode", "token", "developer-tools", "agent-tools"],
        "inputSchema": '{"token":"header.payload.signature"}',
        "outputSchema": '{"verified":false,"header":{},"payload":{}}',
    },
    {
        "slug": "json-canonicalize",
        "title": "capi2 Native · JSON Canonicalize + SHA-256",
        "description": "Canonicalize JSON using sorted keys and compact separators, then return a SHA-256 fingerprint.",
        "category": "Developer Tools",
        "tags": ["json", "canonicalize", "sha256", "fingerprint", "agent-tools"],
        "inputSchema": '{"value":<any JSON value>}',
        "outputSchema": '{"canonical":"...","sha256":"..."}',
    },
]

state = {"ok": False, "status": "starting", "sellerAgentId": None, "offers": [], "errors": []}


def json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode_jwt_part(part):
    pad = "=" * ((4 - len(part) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(part + pad).decode("utf-8"))


def execute(slug, body):
    if slug == "sha256":
        text = body.get("text")
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        return {"algorithm": "sha256", "digest": hashlib.sha256(text.encode()).hexdigest()}
    if slug == "sha512":
        text = body.get("text")
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        return {"algorithm": "sha512", "digest": hashlib.sha512(text.encode()).hexdigest()}
    if slug == "base64-encode":
        text = body.get("text")
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        return {"encoding": "base64", "encoded": base64.b64encode(text.encode()).decode("ascii")}
    if slug == "base64-decode":
        data = body.get("data")
        if not isinstance(data, str):
            raise ValueError("data must be a string")
        return {"encoding": "base64", "decoded": base64.b64decode(data, validate=True).decode("utf-8")}
    if slug == "jwt-decode":
        token = body.get("token")
        if not isinstance(token, str) or len(token.split(".")) < 2:
            raise ValueError("token must be a JWT-shaped string")
        parts = token.split(".")
        return {"verified": False, "header": decode_jwt_part(parts[0]), "payload": decode_jwt_part(parts[1]), "note": "Decoded only; signature not verified."}
    if slug == "json-canonicalize":
        if "value" not in body:
            raise ValueError("value is required")
        canonical = json.dumps(body["value"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {"canonical": canonical, "sha256": hashlib.sha256(canonical.encode()).hexdigest()}
    raise ValueError("unknown operation")


def catalog_titles():
    try:
        r = requests.get(f"{BASE}/api/v1/offers", params={"q": "capi2 Native", "offerType": "api", "limit": 100}, timeout=20)
        r.raise_for_status()
        rows = r.json().get("offers", [])
        return {str(x.get("title", "")): x for x in rows if isinstance(x, dict)}
    except Exception as exc:
        state["errors"].append(f"catalog:{exc.__class__.__name__}")
        return {}


def ensure_offers():
    time.sleep(4)
    wanted = {o["title"] for o in OFFERS}
    existing = catalog_titles()
    if wanted.issubset(existing):
        state["offers"] = [{"title": t, "offerId": existing[t].get("_id"), "buyUrl": existing[t].get("buyUrl")} for t in sorted(wanted)]
        seller_ids = {existing[t].get("sellerId") for t in wanted if existing[t].get("sellerId")}
        state["sellerAgentId"] = next(iter(seller_ids)) if len(seller_ids) == 1 else None
        if len(seller_ids) > 1:
            state["errors"].append("catalog:offers_split_across_multiple_sellers")
        state.update(ok=True, status="already_listed")
        print(f"payan native: already_listed offers={len(state['offers'])}", flush=True)
        return

    key = SELLER_API_KEY
    state["sellerAgentId"] = SELLER_AGENT_ID
    if not key or not SELLER_AGENT_ID:
        if not ALLOW_SELLER_REGISTRATION:
            state["status"] = "seller_identity_missing"
            state["errors"].append(
                "set PAYANAGENT_NATIVE_API_KEY and PAYANAGENT_NATIVE_AGENT_ID; "
                "automatic registration is disabled to prevent duplicate sellers"
            )
            print("payan native: seller_identity_missing; registration disabled", flush=True)
            return
        reg_payload = {
        "name": "capi2 Native Utility APIs",
        "description": "Deterministic paid utility APIs for hashing, Base64, JWT inspection and canonical JSON fingerprints. Hosted for PayanAgent native x402 settlement.",
        "walletAddress": WALLET,
        "chain": "base",
        "tags": ["sha256", "sha512", "base64", "jwt", "json", "agent-tools"],
        "providerType": "api",
        "agentUrl": PUBLIC_ORIGIN,
        }
        r = requests.post(f"{BASE}/api/v1/agents", json=reg_payload, timeout=25)
        if not r.ok:
            state["status"] = "registration_failed"
            state["errors"].append(f"register:{r.status_code}:{r.text[:220]}")
            print(f"payan native: registration_failed status={r.status_code}", flush=True)
            return
        reg = r.json()
        key = reg.get("apiKey")
        state["sellerAgentId"] = reg.get("agentId")
        if not key:
            state["status"] = "registration_failed"
            state["errors"].append("register:no_api_key")
            return
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    created = []
    for offer in OFFERS:
        if offer["title"] in existing:
            row = existing[offer["title"]]
            created.append({"title": offer["title"], "offerId": row.get("_id"), "buyUrl": row.get("buyUrl"), "status": "existing"})
            continue
        endpoint = f"{PUBLIC_ORIGIN}/internal/{RELAY_TOKEN}/{offer['slug']}"
        payload = {
            "title": offer["title"],
            "description": offer["description"],
            "category": offer["category"],
            "tags": offer["tags"],
            "priceCents": 1,
            "offerType": "api",
            "endpoint": endpoint,
            "httpMethod": "POST",
            "inputSchema": offer["inputSchema"],
            "outputSchema": offer["outputSchema"],
            "estimatedDurationSeconds": 2,
            "previewDescription": "Immediate deterministic JSON response after x402 settlement.",
        }
        rr = requests.post(f"{BASE}/api/v1/offers", headers=headers, json=payload, timeout=25)
        if rr.status_code == 201:
            offer_id = rr.json().get("offerId")
            created.append({"title": offer["title"], "offerId": offer_id, "buyUrl": f"/x402/{offer_id}", "status": "created"})
            print(f"payan native: CREATED title={offer['title']} offerId={offer_id}", flush=True)
        else:
            state["errors"].append(f"offer:{offer['title']}:{rr.status_code}:{rr.text[:220]}")
            print(f"payan native: failed title={offer['title']} status={rr.status_code} error={rr.text[:180]}", flush=True)
    state["offers"] = created
    state["ok"] = len(created) == len(OFFERS)
    state["status"] = "listed" if state["ok"] else "partial"
    print(f"payan native: status={state['status']} offers={len(created)}/{len(OFFERS)}", flush=True)
    key = None


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, obj):
        body = json_bytes(obj)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self.send_json(200, {"ok": True, "service": "capi2-payan-native", "marketplace": "PayanAgent", "listing": state})
        return self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        prefix = f"/internal/{RELAY_TOKEN}/"
        path = self.path.split("?", 1)[0]
        if not path.startswith(prefix):
            return self.send_json(404, {"error": "not_found"})
        slug = path[len(prefix):]
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 65536:
                return self.send_json(413, {"error": "body_too_large"})
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
            result = execute(slug, body)
            print(f"payan native: DELIVERED slug={slug}", flush=True)
            return self.send_json(200, {"protocol": "capi2.payan-native/1.0", "operation": slug, "result": result})
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError, base64.binascii.Error) as exc:
            return self.send_json(400, {"error": "invalid_input", "detail": str(exc)[:200]})
        except Exception as exc:
            print(f"payan native: internal_error {exc.__class__.__name__}", flush=True)
            return self.send_json(500, {"error": "internal_error"})

    def log_message(self, *_args):
        return


if __name__ == "__main__":
    threading.Thread(target=ensure_offers, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
