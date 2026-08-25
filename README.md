# genesis-forge-autonomous-earner
The first autonomous money invention engine - creates brand new digital products 24/7
# capi2 revenue operations

`capi2-demand-tools` emits a `capi2.x402.settled` event only from the native
x402 `after_settle` hook. Configure any of these optional destinations:

- `CAPI2_LAGO_WEBHOOK_URL` — usage/billing ingestion bridge
- `CAPI2_TRIGGER_WEBHOOK_URL` — recurring jobs and follow-up workflows
- `CAPI2_CRM_WEBHOOK_URL` — Relaticle or another MCP-capable CRM bridge
- `CAPI2_REVENUE_WEBHOOK_SECRET` — shared HMAC-SHA256 signing secret

Every delivery includes an `Idempotency-Key` and `X-Capi2-Signature`. Buyer
wallets are represented by a one-way hashed `payer_ref`; raw wallet addresses
are not forwarded. Integration failures are logged and never alter x402
verification, settlement, or the paid API response.
