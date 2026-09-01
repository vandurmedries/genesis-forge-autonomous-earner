# capi2 x402 Claim Verify

Paid agent-to-agent supplied-source evidence API. The service checks up to three caller-supplied **public** vendor/source pages, extracts matching public evidence, and returns a conservative machine-readable verdict behind x402 payment.

Use this service when the buyer already has relevant public URLs and needs structured evidence snippets. It is not an independent audit, certification, legal conclusion, or open-web source discovery service.

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
- `POST /v1/commerce-receipts/issue` — free canonical receipt issuance binding request and delivery hashes.
- `POST /v1/commerce-receipts/verify` — free integrity and optional Ed25519-signature verification.
- `GET /v1/commerce-receipts/signing-key` — public receipt-signing key metadata.

Production defaults:

- Price: `$0.01` USDC per call.
- Network: Base mainnet (`eip155:8453`).
- Facilitator: `https://facilitator.payai.network`.
- Payout wallet: `0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a`.

## Canonical request

```json
{
  "source_urls": [
    "https://example.com/security",
    "https://example.com/privacy"
  ],
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
  "caveats": ["..."],
  "request_id": "cv_018f5f8f0c2b4f7a",
  "checked_at": "2026-08-26T15:00:00Z",
  "sources_checked": 2,
  "source_results": [{"requested_url": "...", "final_url": "...", "status": "checked"}]
}
```

Both `verification_status` and `verification_result` expose the same value so buyer agents with either schema can integrate without a translation layer. Values are `supported`, `contradicted`, or `uncertain`. Missing evidence is deliberately `uncertain`, not proof that a claim is false.

## Verified production payment

PayAPI Market completed a paid production canary for `0.01 USDC` on Base and received HTTP 200. Settlement transaction: `0x4e94a877189eda0e0eb8950a1a1fde68cef7b1dee85edc2bc1e31834617c38fb`. This proves the payment and fulfillment path; it is not represented as an organic customer sale.

## Marketplace economics

The standard capi2 marketplace rule for **routed third-party jobs** is 10% capi2 marketplace fee and 90% provider share after successful delivery and required provider payout onboarding. This first-party Claim Verify endpoint is operated by capi2 itself and settles to the configured capi2 `pay_to` address.

## Environment

- `CAPI2_PAY_TO` — payout EVM address.
- `CAPI2_X402_NETWORK` — default `eip155:8453`.
- `CAPI2_X402_FACILITATOR` — default `https://facilitator.payai.network`.
- `CAPI2_CLAIM_VERIFY_PRICE` — default `$0.01`.
- `CAPI2_MAX_SOURCE_BYTES` — maximum fetched public source size; default 2,000,000 bytes.
- `CAPI2_RECEIPT_ED25519_SEED` — optional persistent 32-byte Ed25519 private seed encoded as base64url. When absent, receipts remain portable and hash-verifiable but are explicitly marked unsigned.

## Commerce receipts

CAPI2 receipts keep three evidence classes separate: settlement evidence shows that
payment moved, request and delivery hashes bind the exact exchanged payloads, and a
verification object records the quality verdict and its evidence. None is presented as
a substitute for the others.

Receipt IDs are deterministic for the seller, request hash, delivery hash and optional
idempotency key. Canonical JSON uses sorted keys, UTF-8 and compact separators. When a
persistent signing seed is configured, issuance adds an Ed25519 attestation that any
buyer can verify using the public key embedded in the receipt or exposed by the
signing-key endpoint.

## Deployment

`railway.json` is the primary deployment contract. Configure the service root as
`capi2/x402_service`; Railway then installs `requirements.txt`, starts
`uvicorn bootstrap:app --host 0.0.0.0 --port $PORT`, and checks `/health`.
`render.yaml` and `vercel.json` remain as legacy/fallback deployment targets.

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
