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

## Responsible use

The scanner reads public homepage HTML and response headers. It does not bypass logins or CAPTCHAs and is not intended for private-person enrichment or automated spam. Treat detected technologies and opportunities as reviewable signals rather than certified facts.
