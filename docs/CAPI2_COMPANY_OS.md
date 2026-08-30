# CAPI2 Company OS

## Company thesis

CAPI2 is the evidence infrastructure for autonomous commerce. Payment rails prove that money moved; CAPI2 proves what an agent was allowed to buy, what it requested, what was delivered, how delivery was evaluated, and which settlement belongs to that transaction.

Tagline: **Verifiable commerce for autonomous agents.**

## Product system

1. **Agent Preflight** — policy, authority, recipient and price checks before signing.
2. **Delivery Verify** — evidence-backed comparison of the delivery with the requested outcome.
3. **Commerce Receipt** — portable envelope linking authority, request, delivery, verification and settlement hashes.
4. **Market Radar** — free discovery and normalized market intelligence from public agent-commerce catalogs.

The first two products use the live Claim Verify engine. Commerce Receipt is the primary engineering milestone. Market Radar is the acquisition layer.

## Architecture boundary

- Payment adapters: x402 first; keep evidence contracts payment-rail neutral.
- Verification engine: conservative verdicts with evidence, confidence and caveats.
- Receipt layer: deterministic canonical JSON, hashes, versioned schema and optional signatures.
- Discovery: OpenAPI, `/.well-known/x402`, agent manifest and MCP tools.
- Observability: health, challenge validity, settlement evidence, organic-customer classification and latency.

Never store private keys in the verification service. Never count test or same-operator payments as revenue.

## Commercial wedge

Sell to products that already give agents wallets, escrow or purchasing authority but cannot independently prove delivery quality. Integration partners are more valuable than broad consumer promotion.

Initial offer:

- free discovery and text preflight;
- $0.01 evidence verification;
- integration pilot with machine-readable receipts;
- usage pricing only after a partner proves recurring demand.

## Defensibility

- interoperable receipt schema adopted by multiple agent frameworks;
- verified delivery datasets and evaluation history;
- integrations at the payment, procurement and escrow boundary;
- transparent reliability and settlement evidence;
- conservative trust model that separates payment proof from quality proof.

## Operating metrics

North-star metric: **verified external agent purchases per week**.

Track separately:

- unique external payer wallets;
- organic paid verifications;
- preflight-to-paid conversion;
- repeat payer rate;
- integration partners sending production traffic;
- supported/contradicted/uncertain distribution;
- verification latency and source-fetch failure rate;
- disputes or corrections per 1,000 verifications.

## Build sequence

### Now

- ship the free Market Radar and MCP tool;
- keep Claim Verify and discovery healthy;
- interview or engage wallet, escrow and agent-marketplace builders;
- publish one concrete integration contract, not generic x402 promotion.

### Next

- implement canonical Commerce Receipt issuance;
- add request and delivery SHA-256 binding;
- bind verified x402 settlement metadata to receipts;
- add idempotency and receipt lookup;
- provide TypeScript and Python client examples.

### Then

- partner sandbox and integration dashboard;
- signed receipts and cross-network adapters;
- evaluation policies per buyer;
- recurring commercial plans based on verified usage.

## Decision rules

- Build only capabilities tied to a buyer, integration, reliability gap or measured discovery signal.
- Prefer three qualified integrations over thousands of unqualified impressions.
- Do not promise guaranteed income, universal energy savings or independent certification.
- Keep payments, delivery quality and reputation as distinct evidence classes.
