# CAPI2 AckMint

AckMint is an opt-in delivery layer for webhooks and AI-agent callbacks. A system owner proves control of the callback domain, receives a signed integration token, and sends events through one of three x402-paid delivery routes. A successful route returns an Ed25519-signed receipt retained in PostgreSQL for 90 days.

AckMint never installs itself, scans private systems, or accepts arbitrary internal targets. The receiver must opt in, callback URLs must use public HTTPS, domain proof is required, redirects are blocked, and DNS is checked before every delivery attempt.

## Live endpoints

- Origin: `https://capi2-agent-marketplace-router.onrender.com`
- Human overview: `/`
- API reference: `/docs`
- Agent description: `/.well-known/agent.json`
- x402 discovery: `/.well-known/x402`
- LLM integration notes: `/llms.txt`
- Pricing: `/v1/ackmint/pricing`
- Public signing key: `/v1/ackmint/public-key`

## Pricing

| Tier | x402 fee | Attempts | Success condition |
|---|---:|---:|---|
| Standard | $0.02 USDC | 1 | HTTP 2xx |
| Assured | $0.08 USDC | up to 4 | HTTP 2xx |
| Critical | $0.25 USDC | up to 5 | HTTP 2xx plus explicit event acknowledgement |

The paid route handler only returns success after callback acceptance and receipt persistence. Clients must independently verify the `Payment-Response` header and any referenced on-chain settlement. A database delivery row is not, by itself, proof that revenue settled.

## 1. Prove the callback domain

Request a challenge:

```bash
curl -sS https://capi2-agent-marketplace-router.onrender.com/v1/ackmint/integrations/challenge \
  -H 'content-type: application/json' \
  -d '{
    "callback_url":"https://example.com/webhooks/ackmint",
    "service_name":"Example Orders",
    "integration_ttl_days":365
  }'
```

The response tells you the exact JSON to publish at:

```text
https://example.com/.well-known/ackmint.json
```

After publishing it, exchange the challenge token:

```bash
curl -sS https://capi2-agent-marketplace-router.onrender.com/v1/ackmint/integrations/verify \
  -H 'content-type: application/json' \
  -d '{"challenge_token":"<challenge_token>"}'
```

Store the returned integration token as a secret. It authorizes delivery only to the verified callback URL.

## 2. Deliver an event

Use an x402-capable HTTP client and call a paid route:

```json
{
  "integration_token": "<signed integration token>",
  "event_id": "order_123",
  "event_type": "order.paid",
  "source": "urn:shop:example",
  "payload": {"order_id": "123", "amount": 49.0},
  "idempotency_key": "order_123_paid"
}
```

The idempotency key is unique per integration. Repeating a completed delivery returns a duplicate response instead of sending the event again.

## 3. Receiver acknowledgement

Standard and Assured accept any HTTP 2xx. Critical additionally requires one of:

```http
X-AckMint-Ack: order_123
```

or:

```json
{"accepted": true, "event_id": "order_123"}
```

Each callback receives a CloudEvents-style JSON body plus these headers:

- `Idempotency-Key`
- `X-AckMint-Event-Id`
- `X-AckMint-Body-SHA256`
- `X-AckMint-Signature`
- `X-AckMint-Signing-Key-Id`
- `X-AckMint-Signing-Algorithm`

Verify the exact raw request body before parsing it. Pin or retrieve the public key from `/v1/ackmint/public-key` over HTTPS.

## Clients

- `python/ackmint_client.py`: onboarding helpers and a context-managed x402 paid session.
- `javascript/ackmint.mjs`: browser/Node client that accepts an injected x402-enabled `fetch` implementation.
- `receiver_example.py`: minimal FastAPI callback that verifies the Ed25519 signature and acknowledges an event.

## Human setup service

A one-time setup for one authorized webhook or agent callback is available for €49. The checkout URL is returned by `/v1/ackmint/pricing`. Ongoing x402 delivery fees are separate. No revenue, uptime, or third-party platform approval is guaranteed.
