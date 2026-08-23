# capi2 x402 Claim Verify

Deployable FastAPI service for a paid agent-to-agent vendor-claim check.

## Routes

- `GET /health` — free health/config check.
- `POST /v1/claim-verify` — x402-protected paid route. Default price: `$0.01` in USDC on Base mainnet (`eip155:8453`).

Default payout wallet:

`0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a`

## Environment

- `CAPI2_PAY_TO` — payout EVM address.
- `CAPI2_X402_NETWORK` — default `eip155:8453`.
- `CAPI2_X402_FACILITATOR` — default `https://facilitator.payai.network`.
- `CAPI2_CLAIM_VERIFY_PRICE` — default `$0.01`.

The service uses the x402 FastAPI middleware and EVM exact-payment scheme. Before production promotion, verify the selected facilitator's current Base-mainnet access/auth requirements and run a real low-value settlement test.

## Example unpaid challenge

```bash
curl -i -X POST https://YOUR_HOST/v1/claim-verify \
  -H 'content-type: application/json' \
  -d '{"vendor_url":"https://example.com","claim":"Example provides a published security policy"}'
```

Expected initial response: HTTP 402 with x402 payment requirements.

## Output safety

The endpoint returns public-evidence matching only. It does not certify vendors and must not be used as the sole basis for regulated or high-impact decisions.
