# genesis-forge-autonomous-earner

Machine-readable CAPI2 tools and digital products for autonomous agents.

## Website Buyer Signal Scanner

Turn up to 100 company websites per run into structured prospect intelligence:

- detected CMS, ecommerce, analytics, advertising and infrastructure technology;
- publicly displayed business contacts and social profiles;
- explainable buyer signals such as missing analytics, weak security headers or absent conversion tools;
- stable dataset items for CRM and agent workflows.

**Launch price:** $0.0009 per successful website result ($0.90 per 1,000). Failed scans do not create a billed dataset item.

[Open the Actor on Apify](https://apify.com/capi2/my-actor-1)

### Use from an AI agent

Agents can discover the Actor through Apify's MCP server:

```text
https://mcp.apify.com?tools=capi2/my-actor-1
```

The reusable agent instructions are in [products/website-buyer-signal-scanner/SKILL.md](products/website-buyer-signal-scanner/SKILL.md).

## CAPI2 API Contract Audit on PayAPI Market

CAPI2 API Contract Audit is verified and live on [PayAPI Market](https://payapi.market/api/capi2-api-contract-audit). Agents can discover the paid route through PayAPI's MCP server:

```json
{
  "mcpServers": {
    "payapi": {
      "url": "https://payapi.market/mcp"
    }
  }
}
```

The live CAPI2 Agent Commerce service also publishes its own [x402 discovery document](https://capi2-agent-commerce.vandurmedries.workers.dev/.well-known/x402), [agent card](https://capi2-agent-commerce.vandurmedries.workers.dev/.well-known/agent.json), and [OpenAPI contract](https://capi2-agent-commerce.vandurmedries.workers.dev/openapi.json).

### Higher-value paid routes

| Product | Buyer job | Price |
| --- | --- | ---: |
| [Vendor Risk Pack](https://capi2-agent-commerce.vandurmedries.workers.dev/v1/vendor-risk-pack) | Verify up to five vendor claims and summarize risk | 0.25 USDC |
| [Backtest Integrity Guard](https://capi2-agent-commerce.vandurmedries.workers.dev/v1/backtest-integrity) | Flag missing validation, costs, leakage controls, and reproducibility evidence | 0.20 USDC |
| [Milestone Verifier](https://capi2-agent-commerce.vandurmedries.workers.dev/v1/milestone-verify) | Check delivery evidence against explicit acceptance criteria | 0.15 USDC |
| [Claim Verify](https://capi2-agent-commerce.vandurmedries.workers.dev/v1/claim-verify) | Check one precise claim against up to three public sources | 0.10 USDC |

Each URL is a paid `POST` resource on Base (`eip155:8453`). An unpaid request returns the machine-readable x402 v2 challenge. Settlement proves payment finality, not delivery quality.

## Responsible use

The scanner reads public homepage HTML and response headers. It does not bypass logins or CAPTCHAs and is not intended for private-person enrichment or automated spam. Treat detected technologies and opportunities as reviewable signals rather than certified facts.
