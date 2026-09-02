---
name: capi2-campaign-action-notary
description: Check authority, budget limits and destination evidence immediately before an agent publishes or changes a TikTok advertising campaign. Use for publish_ad, update_budget, change_bid, pause_campaign and resume_campaign actions; it never executes the campaign action itself.
---

# CAPI2 Campaign Action Notary

Run CAPI2 as an independent safety gate immediately before a consequential TikTok Ads mutation.

## Workflow

1. Build an `action` containing its type, advertiser ID, campaign ID when applicable, and proposed budget or bid plus currency when money changes.
2. Build `authority` from current advertiser-approved rules. Include explicit allowed action types and advertiser IDs. For spending changes, include allowed currencies and the corresponding maximum budget or bid.
3. Include approval artifacts as evidence objects with SHA-256 hashes when authority requires evidence.
4. Call the free `POST https://capi2-agent-commerce.vandurmedries.workers.dev/v1/tiktok-ad-preflight` first.
5. Stop on `block`. Ask for explicit human review on `manual_review`.
6. When a verifiable destination check and decision receipt is required, get exact payment terms from `GET https://capi2-agent-commerce.vandurmedries.workers.dev/v1/quote?product_id=tiktok_campaign_notary`.
7. Inspect the unpaid HTTP 402 response from the paid endpoint. Never sign or submit payment without separate buyer approval of the exact amount, asset, network, recipient and resource.
8. After that approval, retry `POST https://capi2-agent-commerce.vandurmedries.workers.dev/v1/tiktok-campaign-notary` with `PAYMENT-SIGNATURE`.
9. Execute the TikTok mutation only when the delivered decision is `allow`. A successful payment is not approval.

Verify receipt integrity for free at `POST https://capi2-agent-commerce.vandurmedries.workers.dev/v1/tiktok-campaign-notary/verify`.

## Required shapes

Budget change:

```json
{
  "action": {
    "type": "update_budget",
    "advertiser_id": "adv_123",
    "campaign_id": "cmp_456",
    "proposed_daily_budget": 250,
    "currency": "EUR"
  },
  "authority": {
    "allowed_action_types": ["update_budget"],
    "allowed_advertiser_ids": ["adv_123"],
    "max_daily_budget": 100,
    "allowed_currencies": ["EUR"],
    "require_evidence_hashes": true
  },
  "evidence": [
    {"kind": "approval", "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
  ]
}
```

Ad publication requires `claim` and a public HTTPS `destination_url` on the action. Put advertiser-specific forbidden phrases in `authority.prohibited_terms`.

## Boundaries

- Never call a TikTok campaign mutation tool from this skill.
- Treat `manual_review` as a stop requiring a person, not as permission.
- CAPI2 is independent and not affiliated with TikTok.
- The result is decision support, not legal advice or TikTok policy approval.
- A receipt proves payload integrity, not that the campaign action executed.
