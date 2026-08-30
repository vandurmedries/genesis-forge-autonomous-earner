# CAPI2 ReceiptRail

ReceiptRail is an **authorized webhook and API reliability rail**. A system owner first proves control of the callback domain. ReceiptRail then accepts paid events, sends a signed CloudEvents-style JSON body to the verified callback, retries according to the selected tier, and returns a signed Ed25519 delivery receipt.

It does not crawl, scan, log in to, or modify third-party systems without permission.

## Why systems integrate it

- Domain proof before a callback is accepted.
- HTTPS-only public callbacks; IP literals, local/private DNS targets and redirects are blocked.
- Idempotency keys and duplicate-fee prevention.
- Signed event bodies and verifiable delivery receipts.
- Bounded retries.
- x402 settlement only after the callback succeeds; handler failures return an error so no service fee settles.

## Prices

| Tier | Fee | Attempts | Success condition |
|---|---:|---:|---|
| standard | $0.02 USDC | 1 | HTTP 2xx |
| assured | $0.10 USDC | 4 | HTTP 2xx |
| critical | $0.50 USDC | 5 | HTTP 2xx plus `X-CAPI2-Ack: <event_id>` or JSON `{ "accepted": true, "event_id": "..." }` |

Network: Base mainnet (`eip155:8453`). Asset: USDC.

## Onboarding

1. `POST /v1/integrations/challenge` with `callback_url` and `service_name`.
2. Publish the exact returned JSON at `https://your-domain/.well-known/capi2-receiptrail.json`.
3. `POST /v1/integrations/verify` with the challenge token.
4. Store the returned signed integration token.
5. Call one of the paid relay routes with an x402-aware client.

Paid routes:

- `POST /v1/relay/standard`
- `POST /v1/relay/assured`
- `POST /v1/relay/critical`

Free routes include `/health`, `/v1/pricing`, `/v1/public-key`, `/v1/receipts/verify`, `/v1/relay/status`, `/.well-known/agent.json` and `/.well-known/x402`.

## Callback headers

ReceiptRail sends:

- `Idempotency-Key`
- `X-CAPI2-Event-Id`
- `X-CAPI2-Body-SHA256`
- `X-CAPI2-Signature`
- `X-CAPI2-Signing-Key-Id`
- `X-CAPI2-Signing-Algorithm: Ed25519`

## Limits of this MVP

Delivery receipts are cached in memory. They survive ordinary requests but not a service restart. A durable database should replace the volatile cache before offering long-term receipt retention or strong cross-instance deduplication.

DNS and URL checks reduce SSRF risk but are not claimed to eliminate every possible network-level attack. Production hardening should add egress controls and IP-pinned DNS resolution.

## Runtime

```bash
pip install -r capi2/receiptrail/requirements.txt
uvicorn capi2.receiptrail.app:app --host 0.0.0.0 --port $PORT
```

Required secret:

```text
CAPI2_RECEIPTRAIL_SIGNING_PRIVATE_KEY_B64
```

It must contain 32 random Ed25519 private-key bytes encoded as URL-safe base64 without padding. Never commit this secret.
