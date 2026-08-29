# CAPI2 / x402 takeover plan

Status: active implementation plan, 2026-08-29.

## Canonical system

`genesis-forge-autonomous-earner` is the canonical CAPI2 backend and operating
repository. It already owns:

- x402 claim verification and demand-tool services;
- Base/USDC payment and discovery contracts;
- settlement telemetry and privacy-preserving revenue webhooks;
- market intelligence, commerce routing and product manifests;
- provider, partner and outreach protocols.

`rarebrief` remains a specialized TypeScript/Cloudflare product surface. Its
five deterministic business resources and Senti watches may be promoted into
the canonical catalog, but it must not become a second source of truth for
payments, buyer identity or revenue reporting.

`atelier-x402` remains an experimental product adapter for paid STL validation,
generation and inference. It is not a production control plane.

## Product portfolio decision

Build and sell narrow, inspectable outputs before broad autonomous services:

1. Evidence-backed claim and vendor verification.
2. API/x402 discovery and health audits.
3. Domain, TLS and public-web intelligence.
4. Persistent monitoring/webhook watches for repeat revenue.
5. Commercial-readiness reports assembled from the same paid primitives.

Do not prioritize generic inference, undifferentiated web search or opaque
"autonomous earner" promises. They have weak differentiation, unpredictable
costs and poor trust characteristics.

## Phase 1: one trustworthy paid loop

The first milestone is complete only when one buyer can:

1. discover a resource through OpenAPI and `/.well-known/x402`;
2. receive a standards-compliant unpaid HTTP 402 challenge;
3. settle on Base in USDC and retry the identical request;
4. receive a deterministic, schema-valid result;
5. see a receipt while CAPI2 records a signed, idempotent settlement event;
6. trigger monitoring without exposing a raw payer wallet;
7. reproduce the flow from public documentation.

Every production service must provide health checks, bounded network access,
timeouts, structured errors, request identifiers, settlement logging and a
documented rollback path.

## Phase 2: recurring revenue

- Package watches and recurring audits above the single-call primitives.
- Keep per-call prices visible and small enough for agent buyers.
- Offer human buyers a fixed-scope commercial audit assembled from the same
  evidence pipeline.
- Measure discovery impressions, 402 challenges, settled calls, repeat payer
  references, delivery cost and gross margin per SKU.

## Release gates

A SKU may move from development to staging when unit and contract tests pass.
It may move to production only when its public schema, price, settlement path,
telemetry, support owner and rollback procedure are verified together.

External outreach and public performance claims require a separate reviewed
release step. Evidence must be retained for every named or quantitative claim.

## Immediate engineering queue

1. Keep Python 3.9 import compatibility for market-intelligence tooling while
   production runtimes migrate to a documented modern Python version.
2. Add an end-to-end contract test for discovery -> 402 -> settlement callback.
3. Normalize product manifests from `rarebrief` into the canonical catalog.
4. Add a single revenue dashboard contract driven by settlement events.
5. Publish buyer documentation only after the contract test is green.
