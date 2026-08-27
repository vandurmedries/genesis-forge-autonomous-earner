# CAPI2 x402 Opportunity Radar

A sellable market-intelligence resource for x402 builders and AI agents.

It ingests public Bazaar discovery listings, normalizes payment terms and service metadata, ranks under-served API categories, benchmarks observable prices, and turns a selected gap into a machine-readable launch brief.

## Product layers

- **Free:** `/v1/snapshot`, `/v1/categories`, `/v1/quote`, `/.well-known/agent.json`, `/llms.txt`
- **Premium:** `/v1/opportunities`, `/v1/catalog`, `/v1/launch-brief`, `/v1/refresh`
- **Commercial offer:** €29 one-time Founding Access through a Stripe Payment Link

Premium requests send either `X-API-Key: ...` or `Authorization: Bearer ...`.

## Run locally

```bash
pip install -r capi2/market_intel/requirements.txt
export FOUNDING_ACCESS_KEY='replace-me'
uvicorn capi2.market_intel.app:app --reload
```

## Environment

| Variable | Purpose |
|---|---|
| `FOUNDING_ACCESS_KEY` | Premium API key delivered after checkout |
| `STRIPE_PAYMENT_LINK` | Live Stripe-hosted checkout URL |
| `PUBLIC_BASE_URL` | Canonical public origin |
| `PAYAI_DISCOVERY_URL` | Public Bazaar catalog source |
| `CDP_BEARER_TOKEN` | Optional Coinbase CDP catalog bearer token |
| `CDP_DISCOVERY_URL` | Optional Coinbase catalog URL override |
| `EXTRA_DISCOVERY_URLS` | Optional comma-separated discovery URLs |
| `CACHE_TTL_SECONDS` | Catalog analysis cache, default 600 seconds |
| `SOURCE_TIMEOUT_SECONDS` | Upstream timeout, default 12 seconds |

## Scoring disclosure

The opportunity score is deliberately auditable:

- 55% catalog scarcity
- 30% disclosed demand prior
- 10% observable price signal
- 5% visible activity signal

It is a prioritization heuristic, not a revenue forecast. Discovery catalogs can be incomplete or stale, so launch briefs include validation gates and require endpoint verification before investment.

## MVP access limitation

The first commercial version uses one shared founding-access key delivered through Stripe's redirect URL. That is suitable for initial paid validation, but it is not per-customer entitlement management. The next security upgrade is a Stripe webhook plus individual revocable API keys.
