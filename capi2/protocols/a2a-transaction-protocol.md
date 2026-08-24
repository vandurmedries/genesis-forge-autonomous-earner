# capi2 A2A Transaction Protocol v0.1

## Purpose

This protocol standardizes how buyer agents, capi2, provider agents, and licensed financial providers exchange transaction metadata without exposing bank/account credentials to capi2.

capi2 is a discovery, routing, marketplace, evidence, and private dispute-review layer. It does not custody customer funds or perform regulated financial execution unless a separately authorized/licensed provider is the executing party.

## Actors

- `buyer_agent` — requests a capability and authorizes payment through its own approved payment rail.
- `capi2_router` — discovers/matches active services and returns the provider route.
- `provider_agent` — performs the purchased non-regulated service.
- `payment_provider` — verifies/settles the payment; capi2 does not receive raw account credentials.
- `licensed_provider` — performs any regulated execution step when required.

## Canonical lifecycle

1. `REQUESTED` — buyer creates a machine-readable transaction intent.
2. `ROUTED` — capi2 selects an active provider/service.
3. `QUOTED` — price, payment protocol, SLA/result mode and provider are fixed for this intent.
4. `PAYMENT_REQUIRED` — provider/payment rail returns the payment requirement (for x402 this is HTTP 402).
5. `PAYMENT_AUTHORIZED` — buyer/payment rail supplies valid authorization/proof. capi2 never stores raw account credentials.
6. `EXECUTING` — provider performs the service.
7. `DELIVERED` — machine-readable result/evidence is returned.
8. `ACCEPTED` — buyer or pre-agreed acceptance policy marks delivery accepted.
9. `SETTLED` — payment rail confirms settlement. For eligible third-party marketplace jobs, economics are 10% capi2 / 90% provider after successful delivery and required payout onboarding.

Optional terminal/exception states:

- `FAILED` — execution or validation failed; no successful-delivery settlement should be released where the payment rail supports cancellation/non-settlement.
- `DISPUTED` — delivery is contested; unreleased payout is paused where technically supported and both parties provide machine-readable evidence.
- `REVERSED` — a payment/provider rail reports an authorized reversal/refund. capi2 records the status but does not impersonate the payment institution.
- `CANCELLED` — buyer cancels before an irreversible payment/execution step where supported.
- `LICENSED_PROVIDER_REQUIRED` — requested action is regulated execution/custody/advice and must be routed to an appropriately licensed/authorized provider or official onboarding flow.

## Required identifiers

Every transaction document uses:

- `transaction_id` — capi2 UUID for correlation.
- `external_id` — optional buyer/customer correlation ID.
- `service_id` — exact active marketplace service.
- `provider_id` — provider identity or marketplace provider application ID.
- `quote_id` or `quote_url` — immutable quote reference when available.
- `payment_reference` — non-secret payment/settlement reference returned by the payment provider.
- `result_reference` — inline result marker or poll URL.

## Standard documents

### Transaction intent

Created by the buyer before payment. Contains capability, constraints, requested action, payment preference, and regulatory classification.

### Route decision

Produced by capi2. Contains match score, selected service, quote URL, payment protocol, execute endpoint, result mode, and policy flags.

### Payment requirement

Produced by the provider/payment rail. Contains only the public payment challenge/requirements and never raw account numbers or credentials.

### Delivery evidence

Produced by the provider. Contains output, evidence references, timestamps, provider/service IDs, and any declared limitations.

### Settlement record

Records success/failure, payment provider reference, amount/asset/network, marketplace economics when applicable, and timestamps. This is bookkeeping metadata; it is not a substitute for the payment provider's authoritative ledger.

### Dispute evidence package

Contains the pre-agreed transaction terms, quote, payment reference, original request, provider result, timestamps, and each party's machine-readable statement. capi2 can provide private marketplace dispute review under pre-agreed terms but is not a court or statutory arbitration body.

## Financial-routing rule

Non-execution analytical services may be routed through capi2, including payments/FX comparison, loan-offer analysis, insurance-policy analysis, payment-fraud/wire-verification, and finance-vendor comparison.

The following are not performed by capi2 or unlicensed agents: custody of funds, investment execution, placing trades, insurance sales/underwriting/binding, lending decisions, or personalized regulated financial advice. These actions transition to `LICENSED_PROVIDER_REQUIRED` and point to a licensed/authorized provider or official onboarding flow.

## Buyer-protection rules

- No provider becomes sellable merely by registering; provider status must be `active` after technical/compliance verification.
- Quotes must identify price, protocol, provider, result mode, and execute endpoint before payment.
- Payment and provider execution errors must remain distinguishable.
- Missing or uncertain evidence must not be represented as successful verification.
- Settlement/release should follow successful delivery and the agreed acceptance rule.
- Transaction events should be append-only in the authoritative event log when persistence is enabled.

## Interoperability

All documents use JSON, UTC ISO-8601 timestamps, stable IDs, explicit `protocol`/`version` fields, and canonical status values. Provider-specific payloads may be nested under `extensions` without changing the core envelope.
