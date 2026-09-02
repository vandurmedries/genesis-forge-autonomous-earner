---
name: website-buyer-signal-scanner
description: Scan public company websites for technology, public business contacts, social profiles, and explainable sales-opportunity signals through the CAPI2 Apify Actor. Use for bulk lead qualification or CRM enrichment; do not use for private-person enrichment or unsolicited mass outreach.
---

# Website Buyer Signal Scanner

Use the public Apify Actor `capi2/my-actor-1` when a workflow needs inexpensive, structured website qualification that other agents can consume through Apify API or MCP.

Actor page: https://apify.com/capi2/my-actor-1

## Input

Provide `startUrls`, `domains`, or both. Set `includeContacts` only when publicly displayed business contact details are relevant. Limit a run to 100 sites.

## Output

Read the default dataset after the run. Each successful website produces one item with the final URL, domain, HTTP status, page metadata, detected technologies, public business contacts and social profiles, plus evidence-based buyer signals and suggested service opportunities.

Treat detected technologies and opportunities as leads for review, not verified facts. Failed inputs do not produce a billed dataset item.

## Agent use

- Prefer Apify MCP when it is already available; otherwise use the Actor API shown on the Actor page.
- Pass dataset items directly to a CRM, scoring agent, or human-reviewed research workflow.
- Preserve evidence fields so downstream agents can explain why a signal was assigned.
- Do not infer sensitive personal information, bypass access controls, or turn public contact discovery into automated spam.

The published launch price is $0.0009 per successful site result. Confirm current pricing on the Actor page before running a paid job.
