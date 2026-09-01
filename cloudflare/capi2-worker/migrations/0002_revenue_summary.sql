CREATE VIEW IF NOT EXISTS revenue_summary AS
SELECT
  route,
  COUNT(*) AS delivered_sales,
  COUNT(DISTINCT transaction_hash) AS unique_settlements,
  SUM(amount_atomic) AS revenue_microusd,
  SUM(estimated_cost_microusd) AS estimated_cost_microusd,
  SUM(amount_atomic) - SUM(estimated_cost_microusd) AS estimated_gross_profit_microusd,
  CASE
    WHEN SUM(amount_atomic) = 0 THEN 0
    ELSE CAST((SUM(amount_atomic) - SUM(estimated_cost_microusd)) * 10000 / SUM(amount_atomic) AS INTEGER)
  END AS estimated_gross_margin_bps,
  MAX(occurred_at) AS last_sale_at
FROM commerce_events
WHERE event_type = 'delivered'
  AND transaction_hash IS NOT NULL
GROUP BY route;
