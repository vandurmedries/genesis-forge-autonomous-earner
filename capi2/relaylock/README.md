# CAPI2 RelayLock

CAPI2 RelayLock is an opt-in reliability layer for webhooks and agent callbacks. It is designed to be integrated deliberately by a system owner; it does not install itself, bypass access controls, or target private networks.

## Revenue model

- One-time integration pilot: EUR 39
- Standard relay: USD 0.02 USDC after successful callback delivery
- Assured relay: USD 0.10 USDC after successful callback delivery, with up to four attempts
- Critical relay: USD 0.50 USDC after successful delivery and explicit receiver acknowledgement, with up to five attempts

Pilot checkout: https://book.stripe.com/aFa8wQ5xr6KJbXwg8Z5Vu0l

## Flow

1. The integrator requests a challenge for a public HTTPS callback.
2. RelayLock validates that the hostname resolves only to public IP addresses.
3. The integrator publishes the exact challenge JSON under `/.well-known/capi2-relaylock.json` on that hostname.
4. RelayLock verifies the proof and returns a signed integration token.
5. An x402 payment-aware client sends an event to a paid relay tier.
6. RelayLock signs the CloudEvent, sends it to the verified callback and applies controlled retries.
7. A success response produces a self-contained Ed25519 delivery receipt; a delivery failure returns an error so the success fee is not treated as earned by the handler.

## Endpoints

- `GET /` — product page
- `GET /docs` — interactive OpenAPI documentation
- `GET /v1/quickstart` — machine-readable installation flow
- `POST /v1/check-callback` — validate callback eligibility
- `POST /v1/integrations/challenge` — begin domain proof
- `POST /v1/integrations/verify` — verify domain proof and mint an integration token
- `POST /v1/relay/standard` — one delivery attempt
- `POST /v1/relay/assured` — controlled retries
- `POST /v1/relay/critical` — retries plus explicit acknowledgement
- `POST /v1/receipts/verify` — verify a RelayLock receipt
- `GET /.well-known/agent.json` — agent discovery manifest
- `GET /.well-known/x402` — paid-resource manifest
- `GET /sdk/javascript` and `GET /sdk/python` — minimal client adapters

## Security boundaries

RelayLock accepts only public HTTPS callback hostnames. It blocks IP-literal callbacks, localhost and common private/internal suffixes, DNS results that are not globally routable, redirects, credentials in URLs, non-443 ports, query strings and fragments. Domain proof is mandatory before an integration token is issued.

The receiver must still authenticate business-level events, durably enforce the supplied idempotency key and store returned receipts. The current free-hosting build keeps only a short-lived hot duplicate guard in process memory; the receipt itself is portable and independently verifiable.

Do not send unnecessary personal data, secrets, credentials, card data or health data in event payloads.

## Run

```bash
pip install -r capi2/receiptrail/requirements.txt
export CAPI2_RELAYLOCK_SIGNING_PRIVATE_KEY_B64='base64url-encoded-32-byte-ed25519-private-key'
export CAPI2_RELAYLOCK_ORIGIN='https://your-relaylock-host.example'
uvicorn capi2.relaylock.app:app --host 0.0.0.0 --port 8000
```

Required production values should be supplied as environment variables. Never commit the signing private key.

## Commercial limits

The pilot covers one callback path, one implementation snippet, one end-to-end test and one signed receipt. It does not include ongoing x402 usage. No uptime, delivery, revenue, savings, certification or regulatory-compliance guarantee is made.
