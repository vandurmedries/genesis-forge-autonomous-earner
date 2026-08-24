# PayanAgent operations

The PayanAgent workers deliberately reuse configured identities. They do not
register a new seller or provider on every process restart.

## Buyer watcher

Required environment variables:

- `PAYANAGENT_API_KEY`
- `PAYANAGENT_AGENT_ID`

Set `CAPI2_ALLOW_PROVIDER_REGISTRATION=true` only for a controlled, one-time
bootstrap. Persist the returned credentials in the deployment secret store,
then disable registration again.

The watcher bids only when the request title explicitly names a supported
deterministic operation and `inputPayload` can be solved before bidding. It
also rejects coordination-only/external-payment requests and checks for an
existing bid from the same agent or payout wallet.

## Native seller

Existing offers are discovered without credentials. Creating missing offers
requires:

- `PAYANAGENT_NATIVE_API_KEY`
- `PAYANAGENT_NATIVE_AGENT_ID`

Set `CAPI2_ALLOW_SELLER_REGISTRATION=true` only for a controlled, one-time
bootstrap. Automatic registration is otherwise fail-closed to avoid splitting
sales and receipt history across duplicate sellers.
