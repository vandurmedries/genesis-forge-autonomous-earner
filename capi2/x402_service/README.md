# capi2 x402 Claim Verify

Paid agent-to-agent vendor-claim verification API. The service fetches a caller-supplied **public** vendor/source page, extracts matching public evidence, and returns a conservative machine-readable verdict behind x402 payment.

## Routes

- `GET /health` — free health/config check.
- `POST /v1/claim-verify` — x402-protected paid route.

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

The same endpoint also accepts the field shapes requested by current capi2 A2A counterparties:

```json
{
  "request_type": "claim_verify",
  "vendor_name": "Example",
  "claim_to_verify": "Example publishes a security policy",
  "context_url": "https://example.com/security"
}
```

and:

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
  "protocol": "capi2.claim_verify/1.1",
  "claim_id": "claim-123",
  "vendor_name": "Example",
  "vendor_url": "https://example.com/security",
  "claim": "Example publishes a security policy",
  "verification_status": "supported",
  "verdict": "SUPPORTED_BY_SUPPLIED_SOURCE",
  "confidence": 0.88,
  "evidence_summary": "...",
  "evidence_source_urls": ["https://example.com/security"],
  "evidence": [{"text": "...", "score": 0.9}],
  "caveats": ["..."]
}
```

`verification_status` is one of `supported`, `contradicted`, or `uncertain`. The service intentionally treats missing evidence as `uncertain`, not as proof that a claim is false.

## Environment

- `CAPI2_PAY_TO` — payout EVM address.
- `CAPI2_X402_NETWORK` — default `eip155:8453`.
- `CAPI2_X402_FACILITATOR` — default `https://facilitator.payai.network`.
- `CAPI2_CLAIM_VERIFY_PRICE` — default `$0.01`.
- `CAPI2_MAX_SOURCE_BYTES` — maximum fetched public source size; default 2,000,000 bytes.

## Deployment

The repository root contains `render.yaml`. It deploys this subdirectory as a public Python web service with `/health` as the health check. `vercel.json` is also retained for Vercel-compatible deployment.

## Unpaid x402 challenge

```bash
curl -i -X POST https://YOUR_HOST/v1/claim-verify \
  -H 'content-type: application/json' \
  -d '{"vendor_url":"https://example.com","claim":"Example provides a published security policy"}'
```

The initial unpaid call must return **HTTP 402** with x402 payment requirements for Base USDC and the configured payout wallet. After payment verification/settlement, the same call returns the JSON result.

## Safety / abuse resistance

- Only public `http`/`https` sources are accepted.
- Localhost, private, link-local, reserved, and other non-global IP destinations are rejected.
- Redirect targets are revalidated and redirect depth is bounded.
- Source response size is bounded.
- Results are public-evidence matching, not vendor certification.
- Regulated or high-impact decisions require independent review.
