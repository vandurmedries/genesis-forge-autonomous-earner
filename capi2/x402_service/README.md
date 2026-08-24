# capi2 x402 Claim Verify

Paid agent-to-agent vendor-claim verification API. The service checks a caller-supplied **public** vendor/source page, extracts matching public evidence, and returns a conservative machine-readable verdict behind x402 payment.

## Autonomous buyer flow

A buyer agent can complete the full transaction without a human sales step:

1. `GET /.well-known/agent.json` — discover capability, schema, price rail and lifecycle.
2. `GET /v1/quote` — obtain the current machine-readable quote.
3. `POST /v1/claim-verify` without payment — receive HTTP `402` with x402 Base/USDC payment requirements.
4. Pay and retry the same request with valid x402 proof — capi2 executes the task.
5. Receive the machine-readable result inline in the successful HTTP `200` response.

FastAPI also exposes `GET /openapi.json` for generic API-aware agents.

## Routes

- `GET /health` — free health/config check.
- `GET /.well-known/agent.json` — free A2A discovery manifest.
- `GET /v1/quote` — free current price/payment/execution quote.
- `GET /v1/claim-verify/schema` — free machine-readable tool/payment schema.
- `POST /v1/claim-verify` — x402-protected paid route; successful response contains the result.

Production defaults:

- Price: `$0.01` USDC per call.
- Network: Base mainnet (`eip155:8453`).
- Facilitator: `https://facilitator.payai.network`.
- Payout wallet: `0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a`.

## Canonical request

```json
{
  "vendor_url": "https://example.com/security",
  "claim": "Example publishes a security policy"
}
```

## Agent-compatible request aliases

```json
{
  "request_type": "claim_verify",
  "vendor_name": "Example",
  "claim_to_verify": "Example publishes a security policy",
  "context_url": "https://example.com/security"
}
```

or:

```json
{
  "claim_id": "claim-123",
  "vendor_url": "https://example.com/security",
  "claim_text": "Example publishes a security policy",
  "verification_type": "public_web_evidence"
}
```

## Response

```json
{
  "protocol": "capi2.claim_verify/1.3",
  "claim_id": "claim-123",
  "vendor_name": "Example",
  "vendor_url": "https://example.com/security",
  "claim": "Example publishes a security policy",
  "verification_status": "supported",
  "verification_result": "supported",
  "verdict": "SUPPORTED_BY_SUPPLIED_SOURCE",
  "confidence": 0.88,
  "evidence_summary": "...",
  "evidence_source_urls": ["https://example.com/security"],
  "evidence": [{"text": "...", "score": 0.9}],
  "caveats": ["..."]
}
```

Both `verification_status` and `verification_result` expose the same value so buyer agents with either schema can integrate without a translation layer. Values are `supported`, `contradicted`, or `uncertain`. Missing evidence is deliberately `uncertain`, not proof that a claim is false.

## Marketplace economics

The standard capi2 marketplace rule for **routed third-party jobs** is 10% capi2 marketplace fee and 90% provider share after successful delivery and required provider payout onboarding. This first-party Claim Verify endpoint is operated by capi2 itself and settles to the configured capi2 `pay_to` address.

## Environment

- `CAPI2_PAY_TO` — payout EVM address.
- `CAPI2_X402_NETWORK` — default `eip155:8453`.
- `CAPI2_X402_FACILITATOR` — default `https://facilitator.payai.network`.
- `CAPI2_CLAIM_VERIFY_PRICE` — default `$0.01`.
- `CAPI2_MAX_SOURCE_BYTES` — maximum fetched public source size; default 2,000,000 bytes.

## Deployment

The repository root contains `render.yaml`, configured for a public Python web service with `/health` as health check. `vercel.json` remains available as an alternate deployment target.

## Unpaid x402 challenge

```bash
curl -i -X POST https://capi2-claim-verify.onrender.com/v1/claim-verify \
  -H 'content-type: application/json' \
  -d '{"vendor_url":"https://example.com","claim":"Example provides a published security policy"}'
```

The initial unpaid call must return **HTTP 402** with x402 payment requirements for Base USDC and the configured payout wallet. After payment verification/settlement, the same request returns the JSON result.

## Safety / abuse resistance

- Only public `http`/`https` sources are accepted.
- Localhost, private, link-local, reserved, and other non-global IP destinations are rejected.
- Redirect targets are revalidated and redirect depth is bounded.
- Source response size is bounded.
- Results are public-evidence matching, not vendor certification.
- Regulated or high-impact decisions require independent review.
