# CAPI2 Cloudflare Worker

Production edge API for CAPI2's x402 offers. It runs independently of Render,
Railway and Vercel and uses Cloudflare D1 as an auditable commerce ledger.

## Revenue rules

- HTTP 402 challenges are demand signals, never revenue.
- Only a successful x402 settlement followed by a successful resource response
  is stored as a delivered sale.
- Buyer wallet addresses are hashed before storage.
- Every paid route declares a conservative cost ceiling.
- The `revenue_summary` view reports settled revenue, estimated cost, gross
  profit and gross margin by route.

## Products

| Route | Price | Function |
| --- | ---: | --- |
| `POST /v1/claim-verify` | $0.10 | Verify one claim against supplied public evidence |
| `POST /v1/vendor-risk-pack` | $0.25 | Verify up to five vendor claims |
| `POST /v1/commerce-receipts/issue` | $0.01 | Issue a deterministic payload-integrity receipt |
| `POST /v1/commerce-receipts/verify` | Free | Verify receipt payload integrity |
| `POST /v1/action-guard` | $0.02 | Stop invalid agent quotes, discounts and bookings |
| `POST /v1/milestone-verify` | $0.15 | Check milestone evidence before escrow release |
| `POST /v1/backtest-integrity` | $0.20 | Detect disclosed backtest methodology failures |
| `POST /v1/ad-claim-guard` | $0.12 | Check an ad claim against its destination |

`GET /v1/action-guard/demo` is a free, non-billable proof showing a wrong
quote and unavailable appointment being blocked.

## Operations

```sh
npm install
npm test
npm run build
npx wrangler deploy --dry-run
npx wrangler deploy
```

Inspect settled revenue without exposing it publicly:

```sh
npx wrangler d1 execute capi2-commerce-ledger --remote \
  --command "SELECT * FROM revenue_summary ORDER BY revenue_microusd DESC"
```

The Worker has structured logging and full Workers observability enabled.
`wrangler tail capi2-agent-commerce` streams production events.
