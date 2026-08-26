# capi2 Agent Intelligence Toolkit

Run public-source intelligence jobs for autonomous agents, procurement teams, vendor-risk workflows and API builders. Every run returns one machine-readable dataset item suitable for agent chaining through the Apify API or MCP server.

## Tools

- **Verify a claim** — compare an exact claim with text from one supplied public webpage.
- **Extract evidence** — return the passages most relevant to a question or claim.
- **Domain intelligence** — collect public DNS, HTTPS, TLS and optional RDAP facts.
- **Live web lookup** — retrieve a public webpage or JSON API and return structured metadata, excerpts and ranked passages.
- **Audit an API** — check OpenAPI, x402, agent manifest, robots, llms and health discovery surfaces.

## Input

Choose `tool` and provide the matching fields:

- `claim_verify`: `url` and `query`
- `evidence_extract`: `url` and `query`
- `domain_intelligence`: `domain`
- `web_lookup`: `url`, with optional `query`
- `api_audit`: `url`

## Output and pricing

Each completed operation writes exactly one structured item to the default dataset and emits the pay-per-event event `result`. Set this Actor to **Pay per event** in Apify Console with `result` as the primary event. Keep Actor permissions limited and Standby mode disabled so the Actor is eligible for agentic x402 discovery.

Recommended initial price: **$0.01 per result**. Apify applies its own platform revenue share and compute costs.

## Safety and limitations

- Public HTTP(S) sources only; private/reserved network targets and embedded credentials are blocked.
- Results are informational and do not certify a vendor, domain or claim.
- Claim verification is lexical evidence analysis, not a substitute for independent review in consequential decisions.
- A missing statement on one supplied page is not proof that a claim is false.
