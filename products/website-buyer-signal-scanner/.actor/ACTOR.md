# Website Buyer Signal Scanner — Tech Stack, Contacts & Buyer Signals

Turn company websites into CRM-ready prospect intelligence for **$0.90 per 1,000 successful sites**. In one request, the Actor detects technology, extracts public business contacts and social profiles, and identifies explainable sales opportunities such as missing analytics, weak security headers, or absent conversion tools.

Use it from the Apify Console, API, schedules, or MCP—no external API key required.

## Why use it?

- Get tech-stack detection, public contact discovery, and buyer signals in one result.
- Generate explainable outreach angles instead of receiving an opaque lead score.
- Process up to 100 websites per run through the Console, API, schedules, or Apify MCP.
- Pay **$0.0009 per successful site**; failed inputs create no dataset item or charge.
- Export clean results to JSON, CSV, Excel, or your CRM workflow.

## Best for

- agencies finding websites that need analytics, conversion, ecommerce, or security work;
- B2B sales teams enriching domain lists before outreach;
- autonomous agents qualifying prospects through Apify MCP or API;
- developers who need lightweight technographic data without a subscription.

## Input

Provide `startUrls`, plain `domains`, or both. Enable `includeContacts` to extract emails, phone numbers, social links, and likely contact pages that are publicly visible on the homepage.

```json
{
  "domains": ["example.com", "shopify.com"],
  "includeContacts": true
}
```

## Output

Each website produces one dataset item containing:

- final URL, domain, HTTP status, title, and description;
- detected CMS, ecommerce, frontend, analytics, advertising, and infrastructure technologies;
- public emails, phone numbers, social links, and contact-page URLs;
- evidence-based buyer signals and corresponding service opportunities.

Example buyer signal:

```json
{
  "signal": "No analytics platform detected",
  "opportunity": "Offer analytics implementation and conversion tracking",
  "evidence": "No known analytics signatures found in the public homepage"
}
```

## Pricing

The Actor uses pay per event. Apify's default dataset-item event is emitted once for each successful website result.

| Usage | Price |
| --- | ---: |
| 1 successful site | $0.0009 |
| 100 successful sites | $0.09 |
| 1,000 successful sites | $0.90 |

Failed inputs are logged but do not create a dataset item or paid event. Apify platform usage is included in the event price.

## Agent and API use

The Actor returns stable, machine-readable dataset items suited to agent chaining. Add `capi2/my-actor-1` to an Apify MCP configuration or call the Actor through the Apify API, then pass the resulting dataset items directly to a CRM, scoring agent, or outreach-review workflow.

## Responsible use and limitations

Only public homepage HTML and response headers are inspected. No login, CAPTCHA bypass, personal-data enrichment, or private-network access is attempted. Technology detection is signature-based and may miss dynamically loaded tools. Contact data must be used in accordance with applicable privacy and anti-spam laws.
