import express from "express";
import { paymentMiddleware, x402ResourceServer } from "@x402/express";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme as ExactEvmServerScheme } from "@x402/evm/exact/server";
import { ExactEvmScheme as ExactEvmClientScheme } from "@x402/evm/exact/client";
import { x402Client, wrapFetchWithPayment } from "@x402/fetch";
import { privateKeyToAccount } from "viem/accounts";

const PORT = Number(process.env.PORT || 3000);
const NETWORK = process.env.CAPI2_X402_NETWORK || "eip155:8453";
const PAY_TO = process.env.CAPI2_PAY_TO || "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a";
const FACILITATOR_URL = process.env.CAPI2_FACILITATOR_URL || "https://facilitator.payai.network";
const AGENT402_ORIGIN = (process.env.CAPI2_AGENT402_ORIGIN || "https://agent402.tools").replace(/\/+$/, "");
const BROKER_ENABLED = String(process.env.CAPI2_BROKER_ENABLED || "false").toLowerCase() === "true";
const BROKER_PRIVATE_KEY = String(process.env.CAPI2_BROKER_PRIVATE_KEY || "").trim();
const DAILY_BUDGET_USD = Number(process.env.CAPI2_BROKER_DAILY_BUDGET_USD || "0.10");

const TIERS = {
  base: { path: "/v1/commerce/execute/base", buyerPrice: "$0.011", buyerPriceUsd: 0.011, upstreamPath: "/api/route/execute", upstreamPriceUsd: 0.01, underlyingMaxUsd: 0.005, capi2MarginUsd: 0.001 },
  plus: { path: "/v1/commerce/execute/plus", buyerPrice: "$0.055", buyerPriceUsd: 0.055, upstreamPath: "/api/route/execute-plus", upstreamPriceUsd: 0.05, underlyingMaxUsd: 0.04, capi2MarginUsd: 0.005 },
};

const spendingAccount = BROKER_PRIVATE_KEY ? privateKeyToAccount(BROKER_PRIVATE_KEY) : null;
const buyerClient = spendingAccount ? new x402Client() : null;
if (buyerClient && spendingAccount) {
  buyerClient.setSpendControls({ maxAmountPerPayment: "$0.05" });
  buyerClient.register("eip155:*", new ExactEvmClientScheme(spendingAccount));
}
const payFetch = buyerClient ? wrapFetchWithPayment(fetch, buyerClient) : null;
const EXECUTION_ARMED = BROKER_ENABLED && Boolean(spendingAccount) && Boolean(payFetch) && Number.isFinite(DAILY_BUDGET_USD) && DAILY_BUDGET_USD > 0;

let budgetDay = new Date().toISOString().slice(0, 10);
let spentUsd = 0;
let reservedUsd = 0;

function resetBudgetIfNeeded() {
  const today = new Date().toISOString().slice(0, 10);
  if (today !== budgetDay) { budgetDay = today; spentUsd = 0; reservedUsd = 0; }
}
function reserveSpend(amountUsd) {
  resetBudgetIfNeeded();
  if (!Number.isFinite(amountUsd) || amountUsd <= 0) return { ok: false, reason: "invalid_spend_amount", release: () => {} };
  if (!Number.isFinite(DAILY_BUDGET_USD) || DAILY_BUDGET_USD <= 0) return { ok: false, reason: "daily_budget_not_configured", release: () => {} };
  if (spentUsd + reservedUsd + amountUsd > DAILY_BUDGET_USD + 1e-9) return { ok: false, reason: "daily_budget_would_be_exceeded", release: () => {} };
  reservedUsd += amountUsd;
  let released = false;
  return { ok: true, release(success = false) { if (released) return; released = true; reservedUsd = Math.max(0, reservedUsd - amountUsd); if (success) spentUsd += amountUsd; } };
}
function decodePaymentResponse(headerValue) {
  if (!headerValue) return null;
  try { return JSON.parse(Buffer.from(headerValue, "base64").toString("utf8")); }
  catch { return { raw: String(headerValue).slice(0, 500) }; }
}
async function readResponse(response) {
  const text = await response.text();
  try { return JSON.parse(text); } catch { return { text: text.slice(0, 20000) }; }
}

const facilitator = new HTTPFacilitatorClient({ url: FACILITATOR_URL });
const resourceServer = new x402ResourceServer(facilitator).register(NETWORK, new ExactEvmServerScheme());
const paymentRoutes = Object.fromEntries(Object.values(TIERS).map((tier) => [
  `POST ${tier.path}`,
  { accepts: [{ scheme: "exact", price: tier.buyerPrice, network: NETWORK, payTo: PAY_TO }], description: `capi2 broker execution tier: buyer pays ${tier.buyerPrice}; capi2 routes and purchases an upstream x402 service up to $${tier.underlyingMaxUsd}.`, mimeType: "application/json" },
]));

const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "64kb" }));
// Critical fail-closed rule: an inactive broker must never issue a payable 402.
// Payment middleware is mounted only after a spending wallet + positive budget are armed.
if (EXECUTION_ARMED) app.use(paymentMiddleware(paymentRoutes, resourceServer));

function publicState() {
  resetBudgetIfNeeded();
  return { broker_enabled: BROKER_ENABLED, execution_armed: EXECUTION_ARMED, spending_wallet_configured: Boolean(spendingAccount), spending_wallet_address: spendingAccount?.address || null, daily_budget_usd: DAILY_BUDGET_USD, spent_today_usd: Number(spentUsd.toFixed(6)), reserved_usd: Number(reservedUsd.toFixed(6)), hard_max_upstream_payment_usd: 0.05 };
}
function tierPublic(name, tier) {
  return { name, method: "POST", path: tier.path, buyer_price_usd: tier.buyerPriceUsd, upstream_route_price_usd: tier.upstreamPriceUsd, underlying_max_usd: tier.underlyingMaxUsd, capi2_margin_usd: tier.capi2MarginUsd };
}

app.get("/health", (_req, res) => res.json({ ok: true, service: "capi2-a2a-broker", version: "2.0.1", network: NETWORK, payout_address: PAY_TO, upstream_router: AGENT402_ORIGIN, ...publicState() }));
app.get("/.well-known/agent.json", (_req, res) => res.json({
  name: "capi2 Agent Commerce Broker", protocol: "capi2.commerce-broker/0.2",
  description: "Buyer pays capi2 once; capi2 buys a bounded upstream x402 route and relays the result with a transparent receipt.",
  free: { health: "/health", manifest: "/.well-known/agent.json", x402: "/.well-known/x402" },
  tiers: Object.fromEntries(Object.entries(TIERS).map(([name, tier]) => [name, tierPublic(name, tier)])),
  execution_state: publicState(),
}));
app.get("/.well-known/x402", (_req, res) => res.json({
  name: "capi2 Agent Commerce Broker", description: "Bounded x402 broker execution through the existing agent-service market.", protocol: "x402", network: NETWORK, asset: "USDC", payTo: PAY_TO,
  active: EXECUTION_ARMED,
  resources: EXECUTION_ARMED ? Object.entries(TIERS).map(([name, tier]) => ({ name: `capi2 broker ${name} tier`, endpoint: `POST ${tier.path}`, method: "POST", price_usd: tier.buyerPriceUsd, summary: `Route and execute a task through an upstream x402 service; capi2 margin $${tier.capi2MarginUsd.toFixed(3)}.` })) : [],
  inactive_reason: EXECUTION_ARMED ? null : "broker_spending_not_armed_no_payable_routes_advertised",
  free_endpoints: ["/health", "/.well-known/agent.json", "/.well-known/x402"],
}));

function validateInput(body, tier) {
  const task = typeof body?.task === "string" ? body.task.trim() : "";
  if (task.length < 3 || task.length > 400) return { error: "task_must_be_3_to_400_chars" };
  const params = body?.params == null ? {} : body.params;
  if (!params || typeof params !== "object" || Array.isArray(params)) return { error: "params_must_be_object" };
  const requestedMax = Number(body?.maxUsd);
  const maxUsd = Number.isFinite(requestedMax) && requestedMax > 0 ? Math.min(requestedMax, tier.underlyingMaxUsd) : tier.underlyingMaxUsd;
  return { task, params, maxUsd };
}
function makeHandler(tierName) {
  const tier = TIERS[tierName];
  return async (req, res) => {
    if (!EXECUTION_ARMED) return res.status(503).json({ error: "broker_spending_not_armed", message: "No payment was requested. Fund/arm the dedicated broker wallet before this route becomes payable.", broker: publicState() });
    const parsed = validateInput(req.body, tier);
    if (parsed.error) return res.status(400).json({ error: parsed.error });
    const reservation = reserveSpend(tier.upstreamPriceUsd);
    if (!reservation.ok) return res.status(503).json({ error: reservation.reason, broker: publicState() });

    const upstreamUrl = `${AGENT402_ORIGIN}${tier.upstreamPath}`;
    const upstreamBody = { task: parsed.task, params: parsed.params, include: "external", maxUsd: parsed.maxUsd };
    try {
      const upstream = await payFetch(upstreamUrl, { method: "POST", headers: { "content-type": "application/json", "user-agent": "capi2-a2a-broker/2.0.1", ...(req.get("idempotency-key") ? { "idempotency-key": `capi2:${req.get("idempotency-key")}` } : {}) }, body: JSON.stringify(upstreamBody) });
      const upstreamPayload = await readResponse(upstream);
      if (!upstream.ok) { reservation.release(false); return res.status(424).json({ error: "upstream_execution_failed", upstream_status: upstream.status, upstream: upstreamPayload, broker: publicState() }); }
      reservation.release(true);
      const settlementHeader = upstream.headers.get("payment-response") || upstream.headers.get("x-payment-response") || upstream.headers.get("PAYMENT-RESPONSE");
      return res.json({ protocol: "capi2.commerce_execution/0.2", status: "delivered", task: parsed.task, result: upstreamPayload, receipt: { tier: tierName, buyer_price_usd: tier.buyerPriceUsd, upstream_route_price_usd: tier.upstreamPriceUsd, capi2_margin_usd: tier.capi2MarginUsd, underlying_max_usd: tier.underlyingMaxUsd, upstream: AGENT402_ORIGIN, upstream_path: tier.upstreamPath, upstream_settlement: decodePaymentResponse(settlementHeader) }, broker: publicState() });
    } catch (error) {
      reservation.release(false);
      return res.status(502).json({ error: "upstream_transport_or_payment_error", detail: String(error?.message || error).slice(0, 500), broker: publicState() });
    }
  };
}
app.post(TIERS.base.path, makeHandler("base"));
app.post(TIERS.plus.path, makeHandler("plus"));
app.use((_req, res) => res.status(404).json({ error: "not_found" }));
app.listen(PORT, "0.0.0.0", () => { console.log(`capi2-a2a-broker listening on ${PORT}`); console.log(`broker enabled=${BROKER_ENABLED} armed=${EXECUTION_ARMED} spendingWallet=${spendingAccount?.address || "not-configured"} budget=$${DAILY_BUDGET_USD}`); });
