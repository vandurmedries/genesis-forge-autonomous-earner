# Website Buyer Signal Scanner

Turn a list of company websites into structured prospect intelligence. Each successful site scan returns detected technologies, publicly displayed contact details, social profiles, and concrete sales opportunities such as missing analytics or security headers.

## Why use it?

- Combine technology detection and public contact discovery in one request.
- Find explainable outreach angles instead of receiving an opaque lead score.
- Process up to 100 websites per run through the Console, API, schedules, or Apify MCP.
- Pay only for successfully scanned websites; failed inputs are returned but are not charged.

## Input

Provide `startUrls`, plain `domains`, or both. Enable `includeContacts` to extract emails, phone numbers, social links, and likely contact pages that are publicly visible on the homepage.

## Output

Each website produces one dataset item containing:

- final URL, domain, HTTP status, title, and description;
- detected CMS, ecommerce, frontend, analytics, advertising, and infrastructure technologies;
- public emails, phone numbers, social links, and contact-page URLs;
- evidence-based buyer signals and corresponding service opportunities.

## Pricing

The Actor uses pay per event. Apify's default dataset-item event is emitted once for each successful website result. Launch price: **$0.0009 per successful site ($0.90 per 1,000)**. Failed inputs are logged but do not create a dataset item or paid event.

## Responsible use and limitations

Only public homepage HTML and response headers are inspected. No login, CAPTCHA bypass, personal-data enrichment, or private-network access is attempted. Technology detection is signature-based and may miss dynamically loaded tools. Contact data must be used in accordance with applicable privacy and anti-spam laws.
