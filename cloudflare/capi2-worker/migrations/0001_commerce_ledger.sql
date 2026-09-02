CREATE TABLE IF NOT EXISTS commerce_events (
  event_id TEXT PRIMARY KEY,
  occurred_at TEXT NOT NULL,
  request_id TEXT NOT NULL,
  route TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK (event_type IN ('challenge', 'settled', 'delivered', 'failed')),
  payer_hash TEXT,
  transaction_hash TEXT,
  amount_atomic INTEGER NOT NULL DEFAULT 0 CHECK (amount_atomic >= 0),
  asset TEXT NOT NULL DEFAULT 'USDC',
  network TEXT NOT NULL,
  estimated_cost_microusd INTEGER NOT NULL DEFAULT 0 CHECK (estimated_cost_microusd >= 0),
  latency_ms INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
  status_code INTEGER NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_commerce_events_tx_delivery
ON commerce_events(transaction_hash, event_type)
WHERE transaction_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_commerce_events_time
ON commerce_events(occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_commerce_events_route_time
ON commerce_events(route, occurred_at DESC);
