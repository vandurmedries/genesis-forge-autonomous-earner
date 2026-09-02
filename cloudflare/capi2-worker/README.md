# CAPI2 Cloudflare Worker

Production edge API for CAPI2's x402 offers. It runs independently of Render,
Railway and Vercel and uses Cloudflare D1 as an auditable commerce ledger.

CAPI2 is positioned as a **programmable notary for autonomous agents**: it
checks an intended action against explicit buyer authority and returns a
tamper-evident decision receipt. This is technical integrity evidence, not
legal notarization or an independent certification that supplied facts are true.

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
| `POST /v1/action-notary` | $0.03 | Check authority and issue an action-decision receipt |
| `POST /v1/tiktok-ad-preflight` | Free | Preview authority and spending-rule failures without executing an ad action |
| `POST /v1/tiktok-campaign-notary` | $0.05 | Gate TikTok ad publication, bid and budget changes and issue a decision receipt |
| `POST /v1/tiktok-campaign-notary/verify` | Free | Verify the campaign-notary receipt integrity |

`GET /v1/tiktok-campaign-notary/demo` shows a €5,000/day budget increase being
blocked by a €250/day authority ceiling. The Agentic Hub submission package is
under `distribution/tiktok-agentic-hub/`.

`GET /v1/action-notary/demo` shows an unauthorized payment being blocked.
`POST /v1/action-notary/verify` verifies receipt integrity without payment.

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
