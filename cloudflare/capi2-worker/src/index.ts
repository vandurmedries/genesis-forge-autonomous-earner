import { env } from "cloudflare:workers";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";
import { bazaarResourceServerExtension, declareDiscoveryExtension } from "@x402/extensions/bazaar";
import { paymentMiddleware, x402ResourceServer } from "@x402/hono";
import { Hono } from "hono";
import { cors } from "hono/cors";

const SERVICE_VERSION = "2.3.0";
const PROTOCOL = `capi2.claim_verify/${SERVICE_VERSION}`;
const USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const MAX_BODY_BYTES = 24_000;
const MAX_SOURCE_BYTES = 160_000;
const MAX_SOURCES = 3;

const PRICES = {
  routeAudit: { display: "$0.008", atomic: 8_000, costCeilingMicrousd: 800 },
  groundingPack: { display: "$0.015", atomic: 15_000, costCeilingMicrousd: 1_500 },
  webExtract: { display: "$0.005", atomic: 5_000, costCeilingMicrousd: 500 },
  paymentSafety: { display: "$0.005", atomic: 5_000, costCeilingMicrousd: 250 },
  claimVerify: { display: "$0.10", atomic: 100_000, costCeilingMicrousd: 20_000 },
  riskPack: { display: "$0.25", atomic: 250_000, costCeilingMicrousd: 50_000 },
  receiptIssue: { display: "$0.01", atomic: 10_000, costCeilingMicrousd: 1_000 },
  actionGuard: { display: "$0.02", atomic: 20_000, costCeilingMicrousd: 1_000 },
  milestoneVerify: { display: "$0.15", atomic: 150_000, costCeilingMicrousd: 15_000 },
  backtestIntegrity: { display: "$0.20", atomic: 200_000, costCeilingMicrousd: 20_000 },
  adClaimGuard: { display: "$0.12", atomic: 120_000, costCeilingMicrousd: 24_000 },
  actionNotary: { display: "$0.03", atomic: 30_000, costCeilingMicrousd: 1_500 },
  tiktokCampaignNotary: { display: "$0.05", atomic: 50_000, costCeilingMicrousd: 5_000 },
} as const;

const PRODUCTS = [
  {
    id: "x402_route_audit",
    method: "POST",
    path: "/v1/x402-route-audit",
    price_usd: 0.008,
    buyer_job: "Probe one public endpoint and diagnose whether agents can discover and parse its unpaid x402 challenge.",
  },
  {
    id: "multi_source_grounding",
    method: "POST",
    path: "/v1/multi-source-grounding",
    price_usd: 0.015,
    buyer_job: "Extract query-relevant text and integrity hashes from up to three buyer-supplied public HTTPS sources.",
  },
  {
    id: "agent_web_extract",
    method: "POST",
    path: "/v1/web-extract",
    price_usd: 0.005,
    buyer_job: "Fetch one public HTTPS page and return compact readable text plus a content hash for agent grounding.",
  },
  {
    id: "x402_buyer_guard",
    method: "POST",
    path: "/v1/x402-payment-safety",
    price_usd: 0.005,
    buyer_job: "Apply a deterministic allow, warn, or block policy to an x402 challenge before signing it.",
  },
  {
    id: "claim_verify",
    method: "POST",
    path: "/v1/claim-verify",
    price_usd: 0.1,
    buyer_job: "Check a precise claim against up to three buyer-supplied public sources.",
  },
  {
    id: "vendor_risk_pack",
    method: "POST",
    path: "/v1/vendor-risk-pack",
    price_usd: 0.25,
    buyer_job: "Verify up to five vendor claims and return a compact risk summary.",
  },
  {
    id: "commerce_receipt",
    method: "POST",
    path: "/v1/commerce-receipts/issue",
    price_usd: 0.01,
    buyer_job: "Bind request and delivery payloads into a deterministic integrity receipt.",
  },
  {
    id: "voice_booking_action_guard",
    method: "POST",
    path: "/v1/action-guard",
    price_usd: 0.02,
    buyer_job: "Block an agent from quoting, booking or discounting when proposed actions conflict with authoritative business rules.",
  },
  {
    id: "milestone_verifier",
    method: "POST",
    path: "/v1/milestone-verify",
    price_usd: 0.15,
    buyer_job: "Check delivery evidence against explicit milestone acceptance criteria before escrow release.",
  },
  {
    id: "backtest_integrity_guard",
    method: "POST",
    path: "/v1/backtest-integrity",
    price_usd: 0.2,
    buyer_job: "Detect missing out-of-sample validation, costs, leakage controls and reproducibility evidence before a trading strategy is trusted.",
  },
  {
    id: "ad_claim_destination_guard",
    method: "POST",
    path: "/v1/ad-claim-guard",
    price_usd: 0.12,
    buyer_job: "Verify an advertisement claim against its public destination before an agent publishes or scales the ad.",
  },
  {
    id: "agent_action_notary",
    method: "POST",
    path: "/v1/action-notary",
    price_usd: 0.03,
    buyer_job: "Check an autonomous action against explicit authority rules and issue a tamper-evident decision receipt before execution.",
  },
  {
    id: "tiktok_campaign_notary",
    method: "POST",
    path: "/v1/tiktok-campaign-notary",
    price_usd: 0.05,
    buyer_job: "Gate a TikTok ad publication or budget change against advertiser authority, destination evidence and spending limits, then issue a verifiable decision receipt.",
  },
] as const;

const workerEnv = env;
const facilitator = new HTTPFacilitatorClient({ url: workerEnv.FACILITATOR_URL });
const resourceServer = new x402ResourceServer(facilitator).register(
  workerEnv.NETWORK,
  new ExactEvmScheme(),
).registerExtension(bazaarResourceServerExtension);

resourceServer.onAfterSettle(async ({ result, requirements }) => {
  console.log(JSON.stringify({
    event: "x402_settled",
    success: result.success,
    transaction: result.transaction,
    network: result.network,
    amount: requirements.amount,
  }));
});

const discoveryExtensions = {
  "/v1/x402-route-audit": declareDiscoveryExtension({
    bodyType: "json",
    input: { url: "https://seller.example/paid-resource", method: "POST" },
    inputSchema: {
      properties: { url: { type: "string", format: "uri" }, method: { type: "string", enum: ["GET", "POST"] } },
      required: ["url"],
    },
    output: { example: { verdict: "ready", status_code: 402, x402_version: 2, findings: [], payment_options: 1 } },
  }),
  "/v1/multi-source-grounding": declareDiscoveryExtension({
    bodyType: "json",
    input: { query: "What are the published security controls?", source_urls: ["https://example.com/security"], max_chars_per_source: 4000 },
    inputSchema: {
      properties: {
        query: { type: "string", minLength: 3, maxLength: 300 },
        source_urls: { type: "array", minItems: 1, maxItems: 3, items: { type: "string", format: "uri" } },
        max_chars_per_source: { type: "integer", minimum: 500, maximum: 5000 },
      },
      required: ["query", "source_urls"],
    },
    output: { example: { query: "security controls", sources_checked: 1, extracts: [{ final_url: "https://example.com/security", text: "...", content_sha256: "..." }] } },
  }),
  "/v1/web-extract": declareDiscoveryExtension({
    bodyType: "json",
    input: { url: "https://example.com/", query: "main product facts", max_chars: 8000 },
    inputSchema: {
      properties: {
        url: { type: "string", format: "uri" },
        query: { type: "string", maxLength: 300 },
        max_chars: { type: "integer", minimum: 500, maximum: 12000 },
      },
      required: ["url"],
    },
    output: { example: { final_url: "https://example.com/", content_type: "text/html", text: "Example Domain...", content_sha256: "...", truncated: false } },
  }),
  "/v1/x402-payment-safety": declareDiscoveryExtension({
    bodyType: "json",
    input: {
      payment_required: { x402Version: 2, resource: { url: "https://seller.example/data" }, accepts: [{ network: "eip155:8453", amount: "10000", asset: USDC, payTo: "0x0000000000000000000000000000000000000001" }] },
      policy: { max_amount_atomic: "10000", allowed_networks: ["eip155:8453"], require_https: true },
    },
    inputSchema: {
      properties: { payment_required: { type: "object" }, policy: { type: "object" } },
      required: ["payment_required", "policy"],
    },
    output: { example: { verdict: "allow", risk_score: 0, findings: [], approved_option: { network: "eip155:8453", amount: "10000" } } },
  }),
  "/v1/claim-verify": declareDiscoveryExtension({
    bodyType: "json",
    input: { vendor_url: "https://example.com/security", claim: "Customer data is encrypted at rest." },
    inputSchema: {
      properties: {
        vendor_url: { type: "string", format: "uri" },
        source_urls: { type: "array", maxItems: 3, items: { type: "string", format: "uri" } },
        claim: { type: "string", minLength: 3, maxLength: 1200 },
      },
      required: ["claim"],
    },
    output: { example: { verification_status: "supported", confidence: 0.88, evidence_source_urls: ["https://example.com/security"] } },
  }),
  "/v1/vendor-risk-pack": declareDiscoveryExtension({
    bodyType: "json",
    input: { claims: [{ vendor_url: "https://example.com/security", claim: "Customer data is encrypted at rest." }] },
    inputSchema: { properties: { claims: { type: "array", minItems: 1, maxItems: 5 } }, required: ["claims"] },
    output: { example: { summary: { supported: 1, contradicted: 0, uncertain: 0 }, reports: [] } },
  }),
  "/v1/commerce-receipts/issue": declareDiscoveryExtension({
    bodyType: "json",
    input: { seller: "https://seller.example/report", request: { claim: "A" }, delivery: { verdict: "supported" } },
    inputSchema: {
      properties: { seller: { type: "string" }, request: { type: "object" }, delivery: { type: "object" } },
      required: ["seller", "request", "delivery"],
    },
    output: { example: { protocol: "capi2.commerce_receipt/1.0", receipt_id: "cr_...", request_sha256: "...", delivery_sha256: "..." } },
  }),
  "/v1/action-guard": declareDiscoveryExtension({
    bodyType: "json",
    input: { proposed_action: { type: "book_and_quote", service_id: "visit", quoted_price: 79, slot: "2026-09-02T14:00:00Z" }, authority: { services: [{ id: "visit", price: 129 }], available_slots: ["2026-09-02T15:00:00Z"], max_discount_percent: 10 } },
    inputSchema: { properties: { proposed_action: { type: "object" }, authority: { type: "object" } }, required: ["proposed_action", "authority"] },
    output: { example: { decision: "block", risk_score: 100, findings: [{ code: "price_mismatch" }] } },
  }),
  "/v1/milestone-verify": declareDiscoveryExtension({
    bodyType: "json",
    input: { criteria: [{ id: "health", description: "Health endpoint returns 200", required: true }], evidence: [{ criterion_id: "health", kind: "test", url: "https://example.com/health", status: "passed", sha256: "abc" }] },
    inputSchema: { properties: { criteria: { type: "array", minItems: 1, maxItems: 20 }, evidence: { type: "array", maxItems: 40 } }, required: ["criteria", "evidence"] },
    output: { example: { decision: "pass", criteria_passed: 1, criteria_failed: 0, manual_review: false } },
  }),
  "/v1/backtest-integrity": declareDiscoveryExtension({
    bodyType: "json",
    input: { report: { strategies_tested: 600, in_sample_period: "2020-2023", out_of_sample_period: "2024", transaction_costs_included: true, slippage_included: true, survivorship_bias_controlled: true, lookahead_bias_controlled: true, benchmark: "buy_and_hold", dataset_hash: "sha256:...", code_hash: "sha256:..." } },
    inputSchema: { properties: { report: { type: "object" } }, required: ["report"] },
    output: { example: { decision: "manual_review", risk_score: 45, findings: [{ code: "multiple_testing_risk" }], simulation_only: true } },
  }),
  "/v1/ad-claim-guard": declareDiscoveryExtension({
    bodyType: "json",
    input: { destination_url: "https://example.com/offer", claim: "Save 30 percent", prohibited_terms: ["guaranteed"] },
    inputSchema: { properties: { destination_url: { type: "string", format: "uri" }, claim: { type: "string", minLength: 3, maxLength: 1200 }, prohibited_terms: { type: "array", maxItems: 30 } }, required: ["destination_url", "claim"] },
    output: { example: { decision: "allow", verification_status: "supported", destination_checked: true } },
  }),
  "/v1/action-notary": declareDiscoveryExtension({
    bodyType: "json",
    input: {
      action: { type: "x402_purchase", amount_atomic: "20000", network: "eip155:8453", recipient: "0x0000000000000000000000000000000000000001" },
      authority: { allowed_action_types: ["x402_purchase"], max_amount_atomic: "50000", allowed_networks: ["eip155:8453"], allowed_recipients: ["0x0000000000000000000000000000000000000001"], require_evidence_hashes: true },
      evidence: [{ kind: "quote", sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }],
    },
    inputSchema: {
      properties: { action: { type: "object" }, authority: { type: "object" }, evidence: { type: "array", maxItems: 20 } },
      required: ["action", "authority", "evidence"],
    },
    output: { example: { decision: "allow", receipt_id: "an_...", integrity: { action_sha256: "...", authority_sha256: "...", evidence_sha256: "..." } } },
  }),
  "/v1/tiktok-campaign-notary": declareDiscoveryExtension({
    bodyType: "json",
    input: {
      action: { type: "update_budget", advertiser_id: "adv_123", campaign_id: "cmp_456", proposed_daily_budget: 250, currency: "EUR" },
      authority: { allowed_action_types: ["update_budget"], allowed_advertiser_ids: ["adv_123"], max_daily_budget: 100, allowed_currencies: ["EUR"], require_evidence_hashes: true },
      evidence: [{ kind: "approval", sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }],
    },
    inputSchema: {
      properties: { action: { type: "object" }, authority: { type: "object" }, evidence: { type: "array", maxItems: 20 } },
      required: ["action", "authority", "evidence"],
    },
    output: { example: { decision: "block", risk_score: 100, receipt_id: "tn_...", findings: [{ code: "budget_above_authority" }] } },
  }),
} as const;

const paidRoutes = {
  "POST /v1/x402-route-audit": {
    accepts: { scheme: "exact", price: PRICES.routeAudit.display, network: workerEnv.NETWORK, payTo: workerEnv.PAY_TO },
    description: "Seller-side compatibility audit for an unpaid x402 route.",
    mimeType: "application/json",
    extensions: discoveryExtensions["/v1/x402-route-audit"],
  },
  "POST /v1/multi-source-grounding": {
    accepts: { scheme: "exact", price: PRICES.groundingPack.display, network: workerEnv.NETWORK, payTo: workerEnv.PAY_TO },
    description: "Query-relevant evidence extracts and hashes from up to three public sources.",
    mimeType: "application/json",
    extensions: discoveryExtensions["/v1/multi-source-grounding"],
  },
  "POST /v1/web-extract": {
    accepts: {
      scheme: "exact",
      price: PRICES.webExtract.display,
      network: workerEnv.NETWORK,
      payTo: workerEnv.PAY_TO,
    },
    description: "Compact readable text and integrity hash from one public HTTPS page.",
    mimeType: "application/json",
    extensions: discoveryExtensions["/v1/web-extract"],
  },
  "POST /v1/x402-payment-safety": {
    accepts: {
      scheme: "exact",
      price: PRICES.paymentSafety.display,
      network: workerEnv.NETWORK,
      payTo: workerEnv.PAY_TO,
    },
    description: "Deterministic buyer-side policy gate for an x402 payment challenge.",
    mimeType: "application/json",
    extensions: discoveryExtensions["/v1/x402-payment-safety"],
  },
  "POST /v1/claim-verify": {
    accepts: {
      scheme: "exact",
      price: PRICES.claimVerify.display,
      network: workerEnv.NETWORK,
      payTo: workerEnv.PAY_TO,
    },
    description: "Evidence-backed verification of one public vendor or product claim.",
    mimeType: "application/json",
    extensions: discoveryExtensions["/v1/claim-verify"],
  },
  "POST /v1/vendor-risk-pack": {
    accepts: {
      scheme: "exact",
      price: PRICES.riskPack.display,
      network: workerEnv.NETWORK,
      payTo: workerEnv.PAY_TO,
    },
    description: "Multi-claim vendor risk and evidence pack.",
    mimeType: "application/json",
    extensions: discoveryExtensions["/v1/vendor-risk-pack"],
  },
  "POST /v1/commerce-receipts/issue": {
    accepts: {
      scheme: "exact",
      price: PRICES.receiptIssue.display,
      network: workerEnv.NETWORK,
      payTo: workerEnv.PAY_TO,
    },
    description: "Issue a deterministic CAPI2 commerce receipt.",
    mimeType: "application/json",
    extensions: discoveryExtensions["/v1/commerce-receipts/issue"],
  },
  "POST /v1/action-guard": {
    accepts: { scheme: "exact", price: PRICES.actionGuard.display, network: workerEnv.NETWORK, payTo: workerEnv.PAY_TO },
    description: "Pre-action authority check for voice, quote and booking agents.", mimeType: "application/json", extensions: discoveryExtensions["/v1/action-guard"],
  },
  "POST /v1/milestone-verify": {
    accepts: { scheme: "exact", price: PRICES.milestoneVerify.display, network: workerEnv.NETWORK, payTo: workerEnv.PAY_TO },
    description: "Acceptance-criteria evidence check before milestone release.", mimeType: "application/json", extensions: discoveryExtensions["/v1/milestone-verify"],
  },
  "POST /v1/backtest-integrity": {
    accepts: { scheme: "exact", price: PRICES.backtestIntegrity.display, network: workerEnv.NETWORK, payTo: workerEnv.PAY_TO },
    description: "Integrity gate for strategy backtests; not investment advice.", mimeType: "application/json", extensions: discoveryExtensions["/v1/backtest-integrity"],
  },
  "POST /v1/ad-claim-guard": {
    accepts: { scheme: "exact", price: PRICES.adClaimGuard.display, network: workerEnv.NETWORK, payTo: workerEnv.PAY_TO },
    description: "Evidence and destination consistency check before ad publication.", mimeType: "application/json", extensions: discoveryExtensions["/v1/ad-claim-guard"],
  },
  "POST /v1/action-notary": {
    accepts: { scheme: "exact", price: PRICES.actionNotary.display, network: workerEnv.NETWORK, payTo: workerEnv.PAY_TO },
    description: "Policy gate and tamper-evident receipt for an autonomous action.", mimeType: "application/json", extensions: discoveryExtensions["/v1/action-notary"],
  },
  "POST /v1/tiktok-campaign-notary": {
    accepts: { scheme: "exact", price: PRICES.tiktokCampaignNotary.display, network: workerEnv.NETWORK, payTo: workerEnv.PAY_TO },
    description: "TikTok campaign authority, claim and budget gate with a verifiable decision receipt.", mimeType: "application/json", extensions: discoveryExtensions["/v1/tiktok-campaign-notary"],
  },
};

const app = new Hono<{ Bindings: Env }>();
let x402Middleware: ReturnType<typeof paymentMiddleware> | undefined;

app.use("*", cors({
  origin: "*",
  allowMethods: ["GET", "POST", "OPTIONS"],
  allowHeaders: ["Content-Type", "PAYMENT-SIGNATURE", "X-PAYMENT", "Idempotency-Key", "X-Request-Id"],
  exposeHeaders: ["PAYMENT-REQUIRED", "PAYMENT-RESPONSE", "X-Request-Id"],
  maxAge: 86_400,
}));
app.use("*", async (c, next) => {
  const started = Date.now();
  const requestId = c.req.header("x-request-id") ?? `req_${crypto.randomUUID().replaceAll("-", "")}`;
  c.header("x-request-id", requestId);
  await next();

  const route = c.req.path;
  const price = priceForRoute(route);
  if (!price) return;

  const settlement = decodeHeader(c.res.headers.get("payment-response"));
  const eventType = settlement?.success === true && c.res.status < 400 ? "delivered" : c.res.status === 402 ? "challenge" : "failed";
  const transaction = typeof settlement?.transaction === "string" ? settlement.transaction : null;
  const payer = typeof settlement?.payer === "string" ? settlement.payer : null;
  const event = {
    event_id: `evt_${crypto.randomUUID().replaceAll("-", "")}`,
    occurred_at: new Date().toISOString(),
    request_id: requestId,
    route,
    event_type: eventType,
    payer_hash: payer ? await sha256Text(payer.toLowerCase()) : null,
    transaction_hash: transaction,
    amount_atomic: eventType === "delivered" ? price.atomic : 0,
    network: c.env.NETWORK,
    estimated_cost_microusd: price.costCeilingMicrousd,
    latency_ms: Date.now() - started,
    status_code: c.res.status,
    metadata_json: JSON.stringify({
      monitor: c.req.header("x-capi2-monitor") === "true",
      traffic_class: trafficClass(c.req.header("user-agent"), c.req.header("referer")),
      payment_attempt: Boolean(paymentHeaderFor(c.req.raw)),
    }),
  };
  c.executionCtx.waitUntil(recordEvent(c.env.DB, event));
  console.log(JSON.stringify({ event: "commerce_request", ...event }));
});
app.use("*", async (c, next) => {
  const price = priceForRoute(c.req.path);
  const isPaidPost = c.req.method === "POST" && price !== null;
  const paymentHeader = c.req.header("payment-signature") ?? c.req.header("x-payment");
  if (!isPaidPost || paymentHeader) return next();

  const description = PRODUCTS.find((product) => product.path === c.req.path)?.buyer_job ?? "CAPI2 paid resource";
  const challenge = {
    x402Version: 2,
    error: "Payment required",
    resource: {
      url: `${c.env.PUBLIC_ORIGIN}${c.req.path}`,
      description,
      mimeType: "application/json",
    },
    accepts: [{
      scheme: "exact",
      network: c.env.NETWORK,
      amount: String(price.atomic),
      asset: USDC,
      payTo: c.env.PAY_TO,
      maxTimeoutSeconds: 300,
      extra: { name: "USD Coin", version: "2" },
    }],
    extensions: withPostMethod(discoveryExtensions[c.req.path as keyof typeof discoveryExtensions]),
  };
  c.header("PAYMENT-REQUIRED", btoa(JSON.stringify(challenge)));
  c.header("Cache-Control", "private, no-store");
  return c.json(challenge, 402);
});
app.use("*", async (c, next) => {
  // The SDK starts facilitator discovery when middleware is constructed. Construct it
  // lazily inside a request because Workers forbids network I/O during module evaluation.
  x402Middleware ??= paymentMiddleware(paidRoutes, resourceServer);
  return x402Middleware(c, next);
});

app.get("/", (c) => c.json({
  service: "CAPI2 Agent Commerce",
  category: "Programmable notary for autonomous agents",
  promise: "Check authority before execution and issue a tamper-evident decision receipt, paid per successful check.",
  version: SERVICE_VERSION,
  recommended_product: {
    id: "tiktok_campaign_notary",
    buyer_job: "Stop unauthorized TikTok ad publications, bids and budget increases before execution and receive a verifiable decision receipt.",
    price: PRICES.tiktokCampaignNotary.display,
    free_demo: `${c.env.PUBLIC_ORIGIN}/v1/tiktok-campaign-notary/demo`,
    free_preflight: `${c.env.PUBLIC_ORIGIN}/v1/tiktok-ad-preflight`,
    quote: `${c.env.PUBLIC_ORIGIN}/v1/quote?product_id=tiktok_campaign_notary`,
  },
  health: `${c.env.PUBLIC_ORIGIN}/health`,
  discovery: `${c.env.PUBLIC_ORIGIN}/.well-known/x402`,
  catalog: `${c.env.PUBLIC_ORIGIN}/v1/buyer-catalog`,
  agent_instructions: `${c.env.PUBLIC_ORIGIN}/llms.txt`,
}));

app.get("/favicon.svg", (c) => c.body(
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#111827"/><path d="M14 20h36v8H22v8h24v8H22v8h-8z" fill="#34d399"/></svg>`,
  200,
  { "content-type": "image/svg+xml", "cache-control": "public, max-age=86400" },
));

app.get("/privacy", (c) => c.json({
  service: "CAPI2 Agent Commerce",
  effective_date: "2026-09-02",
  scope: "API requests to the CAPI2 Cloudflare Worker",
  data_practices: [
    "Request payloads are processed to produce the requested decision and are not intentionally stored in the CAPI2 commerce ledger.",
    "Operational records may include timestamp, route, request identifier, pseudonymous payer hash, settlement transaction hash, amount, network, latency, status and coarse traffic class.",
    "For claim checks, buyer-supplied public HTTPS destinations are fetched solely to produce the requested result.",
    "Cloudflare and payment infrastructure may process technical data under their own terms.",
  ],
  do_not_submit: ["private credentials", "authentication tokens", "personal data not required for the check"],
  contact_url: "https://capi2-agent-commerce.vandurmedries.workers.dev/",
}));

app.get("/terms", (c) => c.json({
  service: "CAPI2 Agent Commerce",
  effective_date: "2026-09-02",
  terms: [
    "CAPI2 is independent and is not affiliated with, endorsed by or approved by TikTok.",
    "Results are automated decision support, not legal advice, platform approval, truth certification or proof that a campaign action executed.",
    "No endpoint publishes an advertisement, changes a bid or budget, or initiates a payment on the buyer's behalf.",
    "The buyer remains responsible for current authority data, campaign compliance and transaction-specific payment approval.",
    "Paid API access is delivered per successful x402 request; settlement alone does not prove output quality.",
  ],
  contact_url: "https://capi2-agent-commerce.vandurmedries.workers.dev/",
}));

app.get("/tiktok-skill.md", (c) => c.text(`# CAPI2 Campaign Action Notary

Use this independent guardrail immediately before an AI agent publishes a TikTok ad, changes a bid or changes a campaign budget.

1. Call POST ${c.env.PUBLIC_ORIGIN}/v1/tiktok-ad-preflight with action, authority and evidence. This is free and never executes a campaign action.
2. Stop when the decision is block. Require human review when the decision is manual_review.
3. For an evidence-backed receipt, get exact terms from GET ${c.env.PUBLIC_ORIGIN}/v1/quote?product_id=tiktok_campaign_notary.
4. Inspect the unpaid HTTP 402 challenge from POST ${c.env.PUBLIC_ORIGIN}/v1/tiktok-campaign-notary.
5. Never sign or submit payment until the buyer separately approves amount, asset, network, recipient and resource.
6. After approved payment, retry with PAYMENT-SIGNATURE and accept execution only when the API decision is allow.
7. Verify receipt integrity for free with POST ${c.env.PUBLIC_ORIGIN}/v1/tiktok-campaign-notary/verify.

Supported action types: publish_ad, update_budget, change_bid, pause_campaign, resume_campaign.

This skill never calls TikTok campaign mutation tools itself. It is not affiliated with TikTok and does not replace TikTok policy or legal review.
`));

app.get("/skill.md", (c) => c.redirect(`${c.env.PUBLIC_ORIGIN}/tiktok-skill.md`, 308));

app.get("/llms.txt", (c) => c.text(`# CAPI2 — Programmable Notary for Autonomous Agents

Use CAPI2 immediately before an autonomous agent buys, quotes, books, publishes, releases a milestone or performs another consequential action.

## Recommended first purchase
- Product: tiktok_campaign_notary
- Buyer outcome: block unauthorized TikTok ad publications, bids and budget increases before execution
- Free proof: GET ${c.env.PUBLIC_ORIGIN}/v1/tiktok-campaign-notary/demo
- Free payload/risk preflight: POST ${c.env.PUBLIC_ORIGIN}/v1/tiktok-ad-preflight
- Quote: GET ${c.env.PUBLIC_ORIGIN}/v1/quote?product_id=tiktok_campaign_notary
- Buy: POST ${c.env.PUBLIC_ORIGIN}/v1/tiktok-campaign-notary
- Verify a receipt for free: POST ${c.env.PUBLIC_ORIGIN}/v1/tiktok-campaign-notary/verify
- Price: ${PRICES.tiktokCampaignNotary.display} USDC on Base (${c.env.NETWORK})
- Recipient: ${c.env.PAY_TO}

## Safe purchase sequence
1. Inspect the free demo.
2. POST /v1/preflight with product_id and payload; this is free.
3. POST the paid resource without a payment header and inspect the HTTP 402 challenge.
4. Obtain buyer approval for amount, asset, network, recipient and resource.
5. Retry with PAYMENT-SIGNATURE and require both PAYMENT-RESPONSE and a successful delivery body.

## Example payload
{"action":{"type":"update_budget","advertiser_id":"adv_123","campaign_id":"cmp_456","proposed_daily_budget":250,"currency":"EUR"},"authority":{"allowed_action_types":["update_budget"],"allowed_advertiser_ids":["adv_123"],"max_daily_budget":100,"allowed_currencies":["EUR"],"require_evidence_hashes":true},"evidence":[{"kind":"approval","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}

All products: ${c.env.PUBLIC_ORIGIN}/v1/buyer-catalog
OpenAPI: ${c.env.PUBLIC_ORIGIN}/openapi.json
`));

app.get("/health", (c) => c.json({
  ok: true,
  service: "capi2-agent-commerce",
  version: SERVICE_VERSION,
  runtime: "cloudflare-workers",
  environment: c.env.ENVIRONMENT,
  network: c.env.NETWORK,
  asset: "USDC",
  pay_to: c.env.PAY_TO,
  paid_resources: PRODUCTS.length,
  checked_at: new Date().toISOString(),
}));

app.get("/.well-known/x402", (c) => c.json({
  version: 1,
  x402Version: 2,
  service: "CAPI2 Agent Commerce",
  network: c.env.NETWORK,
  asset: USDC,
  payTo: c.env.PAY_TO,
  resources: PRODUCTS.map((product) => `${c.env.PUBLIC_ORIGIN}${product.path}`),
  offers: PRODUCTS.map((product) => ({
    ...product,
    resource: `${c.env.PUBLIC_ORIGIN}${product.path}`,
  })),
}));

app.get("/v1/buyer-catalog", (c) => c.json({
  protocol: "capi2.buyer_catalog/2.0",
  settlement: { network: c.env.NETWORK, asset: "USDC", recipient: c.env.PAY_TO },
  margin_policy: { minimum_gross_margin_bps: Number(c.env.MIN_MARGIN_BPS), revenue_basis: "settled external payments only" },
  checkout: {
    steps: [
      "GET /v1/quote?product_id=<id>",
      "POST /v1/preflight with product_id and payload (free)",
      "POST the quoted resource without payment to obtain PAYMENT-REQUIRED",
      "After buyer approval, sign the exact challenge and retry with PAYMENT-SIGNATURE",
      "Treat PAYMENT-RESPONSE plus a successful delivery body as the completed purchase",
    ],
    preflight: `${c.env.PUBLIC_ORIGIN}/v1/preflight`,
  },
  resources: PRODUCTS.map((product) => ({
    ...product,
    quote: `${c.env.PUBLIC_ORIGIN}/v1/quote?product_id=${product.id}`,
    preflight: `${c.env.PUBLIC_ORIGIN}/v1/preflight`,
  })),
}));

app.get("/v1/verifiable-commerce", (c) => c.json({
  protocol: "capi2.verifiable_commerce/1.1",
  category: "Programmable notary for autonomous agents",
  promise: "Authority checks and integrity receipts for autonomous commerce.",
  products: PRODUCTS,
  evidence_policy: [
    "Settlement proves payment finality, not delivery quality.",
    "Receipts bind payload integrity; they do not certify truth.",
    "Revenue reporting counts only settled, successfully delivered requests.",
  ],
}));

app.get("/v1/quote", (c) => {
  const requestedId = c.req.query("product_id") ?? "claim_verify";
  const product = PRODUCTS.find((item) => item.id === requestedId);
  if (!product) return c.json({ error: "unknown product_id", available_product_ids: PRODUCTS.map((item) => item.id) }, 404);
  const price = priceForRoute(product.path)!;
  return c.json({
    protocol: "capi2.quote/2.1",
    product_id: product.id,
    resource: `${c.env.PUBLIC_ORIGIN}${product.path}`,
    method: product.method,
    buyer_job: product.buyer_job,
    price: price.display,
    amount: String(price.atomic),
    decimals: 6,
    asset: "USDC",
    asset_address: USDC,
    network: c.env.NETWORK,
    recipient: c.env.PAY_TO,
    scheme: "exact",
    x402_version: 2,
    preflight: `${c.env.PUBLIC_ORIGIN}/v1/preflight`,
    approval_scope: ["amount", "asset", "network", "recipient", "resource"],
  });
});

app.post("/v1/preflight", async (c) => {
  const input = await readJson(c.req.raw);
  const productId = requiredString(input, "product_id", 3, 100);
  const product = PRODUCTS.find((item) => item.id === productId);
  if (!product) return c.json({ valid: false, billable: false, error: "unknown product_id", available_product_ids: PRODUCTS.map((item) => item.id) }, 422);
  const payload = requireRecord(input.payload, "payload");
  validateProductPayload(productId, payload);
  const price = priceForRoute(product.path)!;
  return c.json({
    protocol: "capi2.preflight/1.0",
    valid: true,
    billable: false,
    product_id: product.id,
    resource: `${c.env.PUBLIC_ORIGIN}${product.path}`,
    exact_payment: { amount: String(price.atomic), display: price.display, asset: "USDC", network: c.env.NETWORK, recipient: c.env.PAY_TO },
    payload_sha256: await sha256Json(payload),
    next: "Request the resource without a payment header to receive the authoritative x402 challenge.",
  });
});

app.get("/v1/free-x402-market-radar", (c) => c.json({
  protocol: "capi2.market_radar/2.0",
  billable: false,
  external_payments_made: false,
  query: c.req.query("q") ?? "agent verification",
  offers: PRODUCTS,
  capi2_positioning: { price_usd: PRICES.claimVerify.atomic / 1_000_000, network: c.env.NETWORK },
}));

app.get("/v1/web-extract/demo", async (c) => {
  const demo = await extractPublicPage("https://example.com/", "example domain", 1_500);
  c.header("Cache-Control", "public, max-age=3600");
  return c.json({ ...demo, billable: false, demo: true, next: `${c.env.PUBLIC_ORIGIN}/v1/quote?product_id=agent_web_extract` });
});

app.get("/v1/action-guard/demo", async (c) => c.json({
  ...(await evaluateActionGuard(
    { type: "book_and_quote", service_id: "visit", quoted_price: 79, slot: "2026-09-02T14:00:00Z" },
    { services: [{ id: "visit", price: 129 }], available_slots: ["2026-09-02T15:00:00Z"], max_discount_percent: 10 },
  )),
  billable: false,
  demo: true,
  next: `${c.env.PUBLIC_ORIGIN}/v1/quote?product_id=voice_booking_action_guard`,
}));

app.get("/v1/action-notary/demo", async (c) => c.json({
  ...(await notarizeAction(
    { type: "x402_purchase", amount_atomic: "75000", network: "eip155:8453", recipient: "0x0000000000000000000000000000000000000002" },
    { allowed_action_types: ["x402_purchase"], max_amount_atomic: "50000", allowed_networks: ["eip155:8453"], allowed_recipients: ["0x0000000000000000000000000000000000000001"], require_evidence_hashes: true },
    [{ kind: "quote", sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }],
  )),
  billable: false,
  demo: true,
  next: `${c.env.PUBLIC_ORIGIN}/v1/quote?product_id=agent_action_notary`,
}));

app.get("/v1/tiktok-campaign-notary/demo", async (c) => c.json({
  ...(await notarizeTikTokCampaignAction(
    { type: "update_budget", advertiser_id: "adv_demo", campaign_id: "cmp_demo", proposed_daily_budget: 5_000, currency: "EUR" },
    { allowed_action_types: ["update_budget"], allowed_advertiser_ids: ["adv_demo"], max_daily_budget: 250, allowed_currencies: ["EUR"], require_evidence_hashes: true },
    [{ kind: "approval", sha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }],
  )),
  billable: false,
  demo: true,
  next: `${c.env.PUBLIC_ORIGIN}/v1/quote?product_id=tiktok_campaign_notary`,
}));

app.post("/v1/tiktok-ad-preflight", async (c) => {
  const input = await readJson(c.req.raw);
  const action = requireRecord(input.action, "action");
  const authority = requireRecord(input.authority, "authority");
  const evidence = objectArray(input.evidence, "evidence", 0, 20);
  validateTikTokCampaignPayload(action, authority, evidence);
  const preview = await notarizeTikTokCampaignAction(action, authority, evidence, false);
  return c.json({
    ...preview,
    protocol: "capi2.tiktok_ad_preflight/1.0",
    billable: false,
    receipt_id: null,
    integrity: null,
    limitations: [
      "Free preflight validates authority and budget rules but does not fetch or verify destination evidence.",
      "No campaign action, publication or payment is executed.",
    ],
    next: `${c.env.PUBLIC_ORIGIN}/v1/quote?product_id=tiktok_campaign_notary`,
  });
});

app.post("/v1/claim-verify/dry-run", async (c) => {
  const input = await readJson(c.req.raw);
  const claim = requiredString(input, "claim", 3, 1_200);
  const evidenceText = requiredString(input, "evidence_text", 3, 8_000);
  return c.json({ ...classifyClaim(claim, [{ requested_url: "inline:evidence", final_url: "inline:evidence", status: "checked", text: bestSnippet(evidenceText, claim) }]), billable: false });
});

app.post("/v1/x402-route-audit", async (c) => {
  const input = await readJson(c.req.raw);
  const url = assertPublicUrl(requiredString(input, "url", 8, 2_000));
  const method = (optionalString(input.method) ?? "POST").toUpperCase();
  if (method !== "GET" && method !== "POST") throw new InputError("method must be GET or POST");
  return c.json(await auditX402Route(url, method));
});

app.post("/v1/action-guard", async (c) => {
  const input = await readJson(c.req.raw);
  return c.json(await evaluateActionGuard(requireRecord(input.proposed_action, "proposed_action"), requireRecord(input.authority, "authority")));
});

app.post("/v1/milestone-verify", async (c) => {
  const input = await readJson(c.req.raw);
  const criteria = objectArray(input.criteria, "criteria", 1, 20);
  const evidence = objectArray(input.evidence, "evidence", 0, 40);
  return c.json(await verifyMilestone(criteria, evidence));
});

app.post("/v1/backtest-integrity", async (c) => {
  const input = await readJson(c.req.raw);
  return c.json(await inspectBacktest(requireRecord(input.report, "report")));
});

app.post("/v1/ad-claim-guard", async (c) => {
  const input = await readJson(c.req.raw);
  const claim = requiredString(input, "claim", 3, 1_200);
  const destination = assertPublicUrl(requiredString(input, "destination_url", 8, 2_000));
  const prohibitedTerms = stringArray(input.prohibited_terms, "prohibited_terms").map((term) => term.toLowerCase());
  const source = await inspectSource(destination, claim);
  const verification = classifyClaim(claim, [source]);
  const { protocol: _claimProtocol, ...verificationResult } = verification;
  const matchedTerms = prohibitedTerms.filter((term) => claim.toLowerCase().includes(term));
  const decision = matchedTerms.length || verification.verification_status === "contradicted" ? "block" : verification.verification_status === "supported" ? "allow" : "manual_review";
  return c.json({ protocol: "capi2.ad_claim_guard/1.0", decision, risk_score: decision === "block" ? 100 : decision === "manual_review" ? 55 : 0, destination_checked: source.status === "checked", matched_prohibited_terms: matchedTerms, ...verificationResult, limitations: ["Checks supplied public destination text only.", "Not legal, advertising-platform or regulatory approval."] });
});

app.post("/v1/action-notary", async (c) => {
  const input = await readJson(c.req.raw);
  const action = requireRecord(input.action, "action");
  const authority = requireRecord(input.authority, "authority");
  const evidence = objectArray(input.evidence, "evidence", 0, 20);
  return c.json(await notarizeAction(action, authority, evidence));
});

app.post("/v1/action-notary/verify", async (c) => {
  const receipt = await readJson(c.req.raw);
  const action = requireRecord(receipt.action, "action");
  const authority = requireRecord(receipt.authority, "authority");
  const evidence = objectArray(receipt.evidence, "evidence", 0, 20);
  const decision = requiredString(receipt, "decision", 3, 30);
  const expected = await actionNotaryIdentity(action, authority, evidence, decision);
  const warnings: string[] = [];
  const integrity = isRecord(receipt.integrity) ? receipt.integrity : {};
  if (receipt.protocol !== "capi2.action_notary/1.0") warnings.push("unsupported_protocol");
  if (integrity.action_sha256 !== expected.action_sha256) warnings.push("action_sha256_mismatch");
  if (integrity.authority_sha256 !== expected.authority_sha256) warnings.push("authority_sha256_mismatch");
  if (integrity.evidence_sha256 !== expected.evidence_sha256) warnings.push("evidence_sha256_mismatch");
  if (receipt.receipt_id !== expected.receipt_id) warnings.push("receipt_id_mismatch");
  return c.json({
    protocol: "capi2.action_notary_verify/1.0",
    valid: warnings.length === 0,
    receipt_id: receipt.receipt_id ?? null,
    warnings,
    verification_scope: "Payload integrity and deterministic policy decision identity; not legal notarization, truth certification or proof of execution.",
  });
});

app.post("/v1/tiktok-campaign-notary", async (c) => {
  const input = await readJson(c.req.raw);
  const action = requireRecord(input.action, "action");
  const authority = requireRecord(input.authority, "authority");
  const evidence = objectArray(input.evidence, "evidence", 0, 20);
  validateTikTokCampaignPayload(action, authority, evidence);
  return c.json(await notarizeTikTokCampaignAction(action, authority, evidence));
});

app.post("/v1/tiktok-campaign-notary/verify", async (c) => {
  const receipt = await readJson(c.req.raw);
  const action = requireRecord(receipt.action, "action");
  const authority = requireRecord(receipt.authority, "authority");
  const evidence = objectArray(receipt.evidence, "evidence", 0, 20);
  const decisionBasis = requireRecord(receipt.decision_basis, "decision_basis");
  const decision = requiredString(receipt, "decision", 3, 30);
  const expected = await tiktokNotaryIdentity(action, authority, evidence, decisionBasis, decision);
  const integrity = isRecord(receipt.integrity) ? receipt.integrity : {};
  const warnings: string[] = [];
  if (receipt.protocol !== "capi2.tiktok_campaign_notary/1.0") warnings.push("unsupported_protocol");
  if (integrity.action_sha256 !== expected.action_sha256) warnings.push("action_sha256_mismatch");
  if (integrity.authority_sha256 !== expected.authority_sha256) warnings.push("authority_sha256_mismatch");
  if (integrity.evidence_sha256 !== expected.evidence_sha256) warnings.push("evidence_sha256_mismatch");
  if (integrity.decision_basis_sha256 !== expected.decision_basis_sha256) warnings.push("decision_basis_sha256_mismatch");
  if (receipt.receipt_id !== expected.receipt_id) warnings.push("receipt_id_mismatch");
  return c.json({
    protocol: "capi2.tiktok_campaign_notary_verify/1.0",
    valid: warnings.length === 0,
    receipt_id: receipt.receipt_id ?? null,
    warnings,
    verification_scope: "Receipt payload integrity only; not TikTok approval, legal review or proof that the campaign action executed.",
  });
});

app.post("/v1/multi-source-grounding", async (c) => {
  const input = await readJson(c.req.raw);
  const query = requiredString(input, "query", 3, 300);
  const urls = sourceUrls(input);
  const maxChars = input.max_chars_per_source === undefined ? 4_000 : Number(input.max_chars_per_source);
  if (!Number.isInteger(maxChars) || maxChars < 500 || maxChars > 5_000) throw new InputError("max_chars_per_source must be an integer between 500 and 5000");
  const settled = await Promise.allSettled(urls.map((url) => extractPublicPage(url, query, maxChars)));
  const extracts: unknown[] = settled.map((result, index) => result.status === "fulfilled"
    ? result.value
    : { requested_url: urls[index], error: result.reason instanceof Error ? result.reason.message : "fetch failed" });
  return c.json({
    protocol: "capi2.multi_source_grounding/1.0",
    query,
    sources_requested: urls.length,
    sources_checked: settled.filter((result) => result.status === "fulfilled").length,
    extracts,
    checked_at: new Date().toISOString(),
    limitations: ["Buyer-supplied public HTTPS sources only.", "Extracted source text is grounding material, not an independent truth certification."],
  });
});

app.post("/v1/web-extract", async (c) => {
  const input = await readJson(c.req.raw);
  const url = assertPublicUrl(requiredString(input, "url", 8, 2_000));
  const query = optionalString(input.query);
  if (query && query.length > 300) throw new InputError("query must contain at most 300 characters");
  const maxChars = input.max_chars === undefined ? 8_000 : Number(input.max_chars);
  if (!Number.isInteger(maxChars) || maxChars < 500 || maxChars > 12_000) throw new InputError("max_chars must be an integer between 500 and 12000");
  return c.json(await extractPublicPage(url, query, maxChars));
});

app.post("/v1/x402-payment-safety", async (c) => {
  const input = await readJson(c.req.raw);
  const paymentRequired = requireRecord(input.payment_required, "payment_required");
  const policy = requireRecord(input.policy, "policy");
  return c.json(await evaluatePaymentSafety(paymentRequired, policy));
});

app.post("/v1/claim-verify", async (c) => {
  const input = await readJson(c.req.raw);
  const claim = requiredString(input, "claim", 3, 1_200);
  const sources = sourceUrls(input);
  const results = await Promise.all(sources.map((url) => inspectSource(url, claim)));
  return c.json(classifyClaim(claim, results));
});

app.post("/v1/vendor-risk-pack", async (c) => {
  const input = await readJson(c.req.raw);
  const claims = input.claims;
  if (!Array.isArray(claims) || claims.length < 1 || claims.length > 5) {
    return c.json({ error: "claims must contain between 1 and 5 items" }, 422);
  }
  const reports = [];
  for (const item of claims) {
    if (!isRecord(item)) return c.json({ error: "each claim must be an object" }, 422);
    const claim = requiredString(item, "claim", 3, 1_200);
    const sources = sourceUrls(item);
    const results = await Promise.all(sources.map((url) => inspectSource(url, claim)));
    reports.push(classifyClaim(claim, results));
  }
  return c.json({
    protocol: "capi2.vendor_risk_pack/2.0",
    reports,
    summary: {
      supported: reports.filter((report) => report.verification_status === "supported").length,
      contradicted: reports.filter((report) => report.verification_status === "contradicted").length,
      uncertain: reports.filter((report) => report.verification_status === "uncertain").length,
    },
    caveat: "Checks only the buyer-supplied public sources.",
  });
});

app.post("/v1/commerce-receipts/issue", async (c) => {
  const input = await readJson(c.req.raw);
  const request = requireRecord(input.request, "request");
  const delivery = requireRecord(input.delivery, "delivery");
  const seller = requiredString(input, "seller", 3, 2_000);
  const requestHash = await sha256Json(request);
  const deliveryHash = await sha256Json(delivery);
  const idempotencyKey = optionalString(input.idempotency_key);
  const identity = { seller, request_sha256: requestHash, delivery_sha256: deliveryHash, idempotency_key: idempotencyKey };
  return c.json({
    protocol: "capi2.commerce_receipt/1.0",
    receipt_id: `cr_${(await sha256Json(identity)).slice(0, 32)}`,
    request_id: optionalString(input.request_id) ?? `req_${crypto.randomUUID().replaceAll("-", "")}`,
    idempotency_key: idempotencyKey,
    seller,
    price: input.price ?? 0.01,
    asset: optionalString(input.asset) ?? "USDC",
    network: optionalString(input.network) ?? c.env.NETWORK,
    request_sha256: requestHash,
    delivery_sha256: deliveryHash,
    request,
    delivery,
    settlement: input.settlement ?? null,
    issued_at: new Date().toISOString(),
    attestation: { signed: false, reason: "worker_signing_key_not_configured" },
    limitations: ["Settlement does not prove delivery quality.", "A content hash proves payload integrity, not truth."],
  });
});

app.post("/v1/commerce-receipts/verify", async (c) => {
  const receipt = await readJson(c.req.raw);
  const request = requireRecord(receipt.request, "request");
  const delivery = requireRecord(receipt.delivery, "delivery");
  const warnings: string[] = [];
  if (receipt.protocol !== "capi2.commerce_receipt/1.0") warnings.push("unsupported_protocol");
  if (receipt.request_sha256 !== await sha256Json(request)) warnings.push("request_sha256_mismatch");
  if (receipt.delivery_sha256 !== await sha256Json(delivery)) warnings.push("delivery_sha256_mismatch");
  if (receipt.attestation && isRecord(receipt.attestation) && receipt.attestation.signed === false) warnings.push("receipt_unsigned");
  const invalidWarnings = warnings.filter((warning) => warning !== "receipt_unsigned");
  return c.json({
    protocol: "capi2.commerce_receipt_verify/1.0",
    valid: invalidWarnings.length === 0,
    integrity_valid: !warnings.some((warning) => warning.endsWith("_mismatch")),
    signature_valid: null,
    warnings,
    receipt_id: receipt.receipt_id ?? null,
    verification_scope: "payload integrity only; settlement and delivery quality are not independently verified",
  });
});

app.get("/openapi.json", (c) => c.json(openApi(c.env.PUBLIC_ORIGIN)));

app.notFound((c) => c.json({ error: "not_found", discovery: "/.well-known/x402" }, 404));
app.onError((error, c) => {
  console.error(JSON.stringify({ event: "unhandled_error", message: error instanceof Error ? error.message : "unknown" }));
  const message = error instanceof InputError ? error.message : "Internal Server Error";
  return c.json({ error: message }, error instanceof InputError ? 422 : 500);
});

export default app;

class InputError extends Error {}

type SourceResult = { requested_url: string; final_url: string; status: "checked" | "failed"; text: string; error?: string };
type CommerceEvent = {
  event_id: string; occurred_at: string; request_id: string; route: string; event_type: string;
  payer_hash: string | null; transaction_hash: string | null; amount_atomic: number; network: string;
  estimated_cost_microusd: number; latency_ms: number; status_code: number;
  metadata_json: string;
};

function priceForRoute(route: string) {
  if (route === "/v1/x402-route-audit") return PRICES.routeAudit;
  if (route === "/v1/multi-source-grounding") return PRICES.groundingPack;
  if (route === "/v1/web-extract") return PRICES.webExtract;
  if (route === "/v1/x402-payment-safety") return PRICES.paymentSafety;
  if (route === "/v1/claim-verify") return PRICES.claimVerify;
  if (route === "/v1/vendor-risk-pack") return PRICES.riskPack;
  if (route === "/v1/commerce-receipts/issue") return PRICES.receiptIssue;
  if (route === "/v1/action-guard") return PRICES.actionGuard;
  if (route === "/v1/milestone-verify") return PRICES.milestoneVerify;
  if (route === "/v1/backtest-integrity") return PRICES.backtestIntegrity;
  if (route === "/v1/ad-claim-guard") return PRICES.adClaimGuard;
  if (route === "/v1/action-notary") return PRICES.actionNotary;
  if (route === "/v1/tiktok-campaign-notary") return PRICES.tiktokCampaignNotary;
  return null;
}

function paymentHeaderFor(request: Request): string | null {
  return request.headers.get("payment-signature") ?? request.headers.get("x-payment");
}

function trafficClass(userAgent: string | undefined, referer: string | undefined): string {
  const value = `${userAgent ?? ""} ${referer ?? ""}`.toLowerCase();
  if (value.includes("capi2") || value.includes("monitor")) return "internal_or_monitor";
  if (value.includes("x402scan") || value.includes("agentcash") || value.includes("scanner") || value.includes("bot")) return "marketplace_or_bot";
  if (value.includes("mozilla") || value.includes("chrome") || value.includes("safari")) return "browser";
  return "unknown_client";
}

function validateProductPayload(productId: string, payload: Record<string, unknown>): void {
  if (productId === "x402_route_audit") {
    assertPublicUrl(requiredString(payload, "url", 8, 2_000));
    const method = (optionalString(payload.method) ?? "POST").toUpperCase();
    if (method !== "GET" && method !== "POST") throw new InputError("method must be GET or POST");
    return;
  }
  if (productId === "multi_source_grounding") {
    requiredString(payload, "query", 3, 300);
    sourceUrls(payload);
    if (payload.max_chars_per_source !== undefined) {
      const maxChars = Number(payload.max_chars_per_source);
      if (!Number.isInteger(maxChars) || maxChars < 500 || maxChars > 5_000) throw new InputError("max_chars_per_source must be an integer between 500 and 5000");
    }
    return;
  }
  if (productId === "agent_web_extract") {
    assertPublicUrl(requiredString(payload, "url", 8, 2_000));
    const query = optionalString(payload.query);
    if (query && query.length > 300) throw new InputError("query must contain at most 300 characters");
    if (payload.max_chars !== undefined) {
      const maxChars = Number(payload.max_chars);
      if (!Number.isInteger(maxChars) || maxChars < 500 || maxChars > 12_000) throw new InputError("max_chars must be an integer between 500 and 12000");
    }
    return;
  }
  if (productId === "x402_buyer_guard") {
    requireRecord(payload.payment_required, "payment_required");
    const policy = requireRecord(payload.policy, "policy");
    const maxAmount = requiredString(policy, "max_amount_atomic", 1, 40);
    if (!/^\d+$/.test(maxAmount)) throw new InputError("max_amount_atomic must be an unsigned integer string");
    stringArray(policy.allowed_networks, "allowed_networks");
    stringArray(policy.allowed_assets, "allowed_assets");
    stringArray(policy.allowed_recipients, "allowed_recipients");
    return;
  }
  if (productId === "claim_verify") {
    requiredString(payload, "claim", 3, 1_200);
    sourceUrls(payload);
    return;
  }
  if (productId === "vendor_risk_pack") {
    if (!Array.isArray(payload.claims) || payload.claims.length < 1 || payload.claims.length > 5) {
      throw new InputError("claims must contain between 1 and 5 items");
    }
    for (const item of payload.claims) {
      const claim = requireRecord(item, "each claim");
      requiredString(claim, "claim", 3, 1_200);
      sourceUrls(claim);
    }
    return;
  }
  if (productId === "commerce_receipt") {
    requiredString(payload, "seller", 3, 2_000);
    requireRecord(payload.request, "request");
    requireRecord(payload.delivery, "delivery");
    return;
  }
  if (productId === "voice_booking_action_guard") {
    requireRecord(payload.proposed_action, "proposed_action");
    requireRecord(payload.authority, "authority");
    return;
  }
  if (productId === "milestone_verifier") {
    objectArray(payload.criteria, "criteria", 1, 20);
    objectArray(payload.evidence, "evidence", 0, 40);
    return;
  }
  if (productId === "backtest_integrity_guard") {
    requireRecord(payload.report, "report");
    return;
  }
  if (productId === "ad_claim_destination_guard") {
    assertPublicUrl(requiredString(payload, "destination_url", 8, 2_000));
    requiredString(payload, "claim", 3, 1_200);
    stringArray(payload.prohibited_terms, "prohibited_terms");
    return;
  }
  if (productId === "agent_action_notary") {
    requireRecord(payload.action, "action");
    requireRecord(payload.authority, "authority");
    objectArray(payload.evidence, "evidence", 0, 20);
    return;
  }
  if (productId === "tiktok_campaign_notary") {
    const action = requireRecord(payload.action, "action");
    const authority = requireRecord(payload.authority, "authority");
    const evidence = objectArray(payload.evidence, "evidence", 0, 20);
    validateTikTokCampaignPayload(action, authority, evidence);
    return;
  }
  throw new InputError("unknown product_id");
}

function objectArray(value: unknown, field: string, min: number, max: number): Record<string, unknown>[] {
  if (!Array.isArray(value) || value.length < min || value.length > max || value.some((item) => !isRecord(item))) {
    throw new InputError(`${field} must contain ${min}-${max} objects`);
  }
  return value as Record<string, unknown>[];
}

async function evaluateActionGuard(action: Record<string, unknown>, authority: Record<string, unknown>) {
  const findings: Array<{ severity: "warn" | "block"; code: string; message: string }> = [];
  const serviceId = requiredString(action, "service_id", 1, 120);
  const services = objectArray(authority.services, "authority.services", 1, 100);
  const service = services.find((item) => optionalString(item.id) === serviceId);
  if (!service) findings.push({ severity: "block", code: "unknown_service", message: "Service is absent from the authoritative catalog." });
  const quotedPrice = Number(action.quoted_price);
  const authoritativePrice = service ? Number(service.price) : NaN;
  if (!Number.isFinite(quotedPrice) || quotedPrice < 0) findings.push({ severity: "block", code: "invalid_price", message: "Proposed price is not a non-negative number." });
  if (service && Number.isFinite(authoritativePrice) && quotedPrice !== authoritativePrice) {
    const discount = authoritativePrice > 0 ? ((authoritativePrice - quotedPrice) / authoritativePrice) * 100 : 0;
    const maxDiscount = Number(authority.max_discount_percent ?? 0);
    findings.push({ severity: discount > maxDiscount ? "block" : "warn", code: "price_mismatch", message: `Quoted price ${quotedPrice} differs from authoritative price ${authoritativePrice}.` });
  }
  const slot = optionalString(action.slot);
  const slots = stringArray(authority.available_slots, "authority.available_slots");
  if (slot && !slots.includes(slot)) findings.push({ severity: "block", code: "slot_unavailable", message: "Requested slot is absent from current availability." });
  const decision = findings.some((item) => item.severity === "block") ? "block" : findings.length ? "manual_review" : "allow";
  return { protocol: "capi2.action_guard/1.0", billable: true, decision, risk_score: decision === "block" ? 100 : decision === "manual_review" ? 40 : 0, findings, action_sha256: await sha256Json(action), authority_sha256: await sha256Json(authority), limitations: ["Authority data is buyer-supplied and must be kept current.", "No booking, quote, message or payment is executed by this check."] };
}

async function actionNotaryIdentity(action: Record<string, unknown>, authority: Record<string, unknown>, evidence: Record<string, unknown>[], decision: string) {
  const actionSha256 = await sha256Json(action);
  const authoritySha256 = await sha256Json(authority);
  const evidenceSha256 = await sha256Json(evidence);
  const receiptId = `an_${(await sha256Json({ action_sha256: actionSha256, authority_sha256: authoritySha256, evidence_sha256: evidenceSha256, decision })).slice(0, 40)}`;
  return { receipt_id: receiptId, action_sha256: actionSha256, authority_sha256: authoritySha256, evidence_sha256: evidenceSha256 };
}

async function notarizeAction(action: Record<string, unknown>, authority: Record<string, unknown>, evidence: Record<string, unknown>[]) {
  const findings: Array<{ severity: "warn" | "block"; code: string; message: string }> = [];
  const actionType = requiredString(action, "type", 1, 120);
  const allowedActionTypes = stringArray(authority.allowed_action_types, "authority.allowed_action_types");
  if (!allowedActionTypes.length || !allowedActionTypes.includes(actionType)) {
    findings.push({ severity: "block", code: "action_type_not_allowed", message: "Action type is absent from the authority allow-list." });
  }

  const amountText = optionalString(action.amount_atomic);
  const maxAmountText = optionalString(authority.max_amount_atomic);
  if (amountText !== null || maxAmountText !== null) {
    if (!amountText || !/^\d+$/.test(amountText)) findings.push({ severity: "block", code: "invalid_amount", message: "Action amount_atomic must be an unsigned integer string." });
    if (!maxAmountText || !/^\d+$/.test(maxAmountText)) findings.push({ severity: "block", code: "invalid_amount_limit", message: "Authority max_amount_atomic must be an unsigned integer string." });
    if (amountText && maxAmountText && /^\d+$/.test(amountText) && /^\d+$/.test(maxAmountText) && BigInt(amountText) > BigInt(maxAmountText)) {
      findings.push({ severity: "block", code: "amount_above_authority", message: "Action amount exceeds the authoritative limit." });
    }
  }

  const network = optionalString(action.network);
  const allowedNetworks = stringArray(authority.allowed_networks, "authority.allowed_networks");
  if (network && allowedNetworks.length && !allowedNetworks.includes(network)) {
    findings.push({ severity: "block", code: "network_not_allowed", message: "Action network is absent from the authority allow-list." });
  }

  const recipient = optionalString(action.recipient);
  const allowedRecipients = stringArray(authority.allowed_recipients, "authority.allowed_recipients").map((value) => value.toLowerCase());
  if (recipient && allowedRecipients.length && !allowedRecipients.includes(recipient.toLowerCase())) {
    findings.push({ severity: "block", code: "recipient_not_allowed", message: "Action recipient is absent from the authority allow-list." });
  }

  if (authority.require_evidence_hashes === true) {
    if (!evidence.length) findings.push({ severity: "block", code: "evidence_required", message: "Authority requires at least one evidence item." });
    if (evidence.some((item) => !/^[a-fA-F0-9]{64}$/.test(optionalString(item.sha256) ?? ""))) {
      findings.push({ severity: "block", code: "invalid_evidence_hash", message: "Every evidence item must contain a 64-character SHA-256 hash." });
    }
  }

  const decision = findings.some((item) => item.severity === "block") ? "block" : findings.length ? "manual_review" : "allow";
  const identity = await actionNotaryIdentity(action, authority, evidence, decision);
  return {
    protocol: "capi2.action_notary/1.0",
    billable: true,
    decision,
    risk_score: decision === "block" ? 100 : decision === "manual_review" ? 40 : 0,
    receipt_id: identity.receipt_id,
    integrity: { action_sha256: identity.action_sha256, authority_sha256: identity.authority_sha256, evidence_sha256: identity.evidence_sha256 },
    action,
    authority,
    evidence,
    findings,
    issued_at: new Date().toISOString(),
    limitations: ["Tamper-evident integrity receipt, not legal notarization or truth certification.", "No action, message, booking, publication or payment is executed by this service."],
  };
}

function validateTikTokCampaignPayload(action: Record<string, unknown>, authority: Record<string, unknown>, evidence: Record<string, unknown>[]): void {
  const actionType = requiredString(action, "type", 3, 120);
  const supported = ["publish_ad", "update_budget", "change_bid", "pause_campaign", "resume_campaign"];
  if (!supported.includes(actionType)) throw new InputError(`action.type must be one of: ${supported.join(", ")}`);
  requiredString(action, "advertiser_id", 1, 160);
  stringArray(authority.allowed_action_types, "authority.allowed_action_types");
  stringArray(authority.allowed_advertiser_ids, "authority.allowed_advertiser_ids");
  stringArray(authority.allowed_currencies, "authority.allowed_currencies");
  stringArray(authority.prohibited_terms, "authority.prohibited_terms");
  if (evidence.length > 20) throw new InputError("evidence must contain at most 20 objects");
  if (actionType === "publish_ad") {
    requiredString(action, "claim", 3, 1_200);
    assertPublicUrl(requiredString(action, "destination_url", 8, 2_000));
  }
  if (actionType === "update_budget" || actionType === "change_bid") {
    const proposed = Number(actionType === "update_budget" ? action.proposed_daily_budget : action.proposed_bid);
    if (!Number.isFinite(proposed) || proposed < 0) throw new InputError(`${actionType === "update_budget" ? "proposed_daily_budget" : "proposed_bid"} must be a non-negative number`);
    requiredString(action, "currency", 3, 12);
  }
}

async function tiktokNotaryIdentity(
  action: Record<string, unknown>, authority: Record<string, unknown>, evidence: Record<string, unknown>[],
  decisionBasis: Record<string, unknown>, decision: string,
) {
  const actionSha256 = await sha256Json(action);
  const authoritySha256 = await sha256Json(authority);
  const evidenceSha256 = await sha256Json(evidence);
  const decisionBasisSha256 = await sha256Json(decisionBasis);
  const receiptId = `tn_${(await sha256Json({ action_sha256: actionSha256, authority_sha256: authoritySha256, evidence_sha256: evidenceSha256, decision_basis_sha256: decisionBasisSha256, decision })).slice(0, 40)}`;
  return { receipt_id: receiptId, action_sha256: actionSha256, authority_sha256: authoritySha256, evidence_sha256: evidenceSha256, decision_basis_sha256: decisionBasisSha256 };
}

async function notarizeTikTokCampaignAction(
  action: Record<string, unknown>, authority: Record<string, unknown>, evidence: Record<string, unknown>[], verifyDestination = true,
) {
  validateTikTokCampaignPayload(action, authority, evidence);
  const findings: Array<{ severity: "warn" | "block"; code: string; message: string }> = [];
  const actionType = requiredString(action, "type", 3, 120);
  const advertiserId = requiredString(action, "advertiser_id", 1, 160);
  const allowedActionTypes = stringArray(authority.allowed_action_types, "authority.allowed_action_types");
  const allowedAdvertiserIds = stringArray(authority.allowed_advertiser_ids, "authority.allowed_advertiser_ids");

  if (!allowedActionTypes.includes(actionType)) findings.push({ severity: "block", code: "action_type_not_allowed", message: "Campaign action is absent from the authority allow-list." });
  if (!allowedAdvertiserIds.includes(advertiserId)) findings.push({ severity: "block", code: "advertiser_not_allowed", message: "Advertiser account is absent from the authority allow-list." });

  const currency = optionalString(action.currency)?.toUpperCase() ?? null;
  const allowedCurrencies = stringArray(authority.allowed_currencies, "authority.allowed_currencies").map((value) => value.toUpperCase());
  if (currency && (!allowedCurrencies.length || !allowedCurrencies.includes(currency))) {
    findings.push({ severity: "block", code: "currency_not_allowed", message: "Campaign currency is absent from the authority allow-list." });
  }

  if (actionType === "update_budget") {
    const proposed = Number(action.proposed_daily_budget);
    const maximum = Number(authority.max_daily_budget);
    if (!Number.isFinite(maximum) || maximum < 0) findings.push({ severity: "block", code: "missing_budget_limit", message: "Authority must declare a non-negative max_daily_budget." });
    else if (proposed > maximum) findings.push({ severity: "block", code: "budget_above_authority", message: `Proposed daily budget ${proposed} exceeds the authoritative limit ${maximum}.` });
  }
  if (actionType === "change_bid") {
    const proposed = Number(action.proposed_bid);
    const maximum = Number(authority.max_bid);
    if (!Number.isFinite(maximum) || maximum < 0) findings.push({ severity: "block", code: "missing_bid_limit", message: "Authority must declare a non-negative max_bid." });
    else if (proposed > maximum) findings.push({ severity: "block", code: "bid_above_authority", message: `Proposed bid ${proposed} exceeds the authoritative limit ${maximum}.` });
  }

  if (authority.require_evidence_hashes === true) {
    if (!evidence.length) findings.push({ severity: "block", code: "evidence_required", message: "Authority requires hashed approval evidence." });
    if (evidence.some((item) => !/^[a-fA-F0-9]{64}$/.test(optionalString(item.sha256) ?? ""))) {
      findings.push({ severity: "block", code: "invalid_evidence_hash", message: "Every evidence item must contain a 64-character SHA-256 hash." });
    }
  }

  let claimResult: Record<string, unknown> | null = null;
  if (actionType === "publish_ad") {
    const claim = requiredString(action, "claim", 3, 1_200);
    const prohibitedTerms = stringArray(authority.prohibited_terms, "authority.prohibited_terms").map((term) => term.toLowerCase());
    const matchedTerms = prohibitedTerms.filter((term) => claim.toLowerCase().includes(term));
    if (matchedTerms.length) findings.push({ severity: "block", code: "prohibited_claim_term", message: `Claim contains prohibited terms: ${matchedTerms.join(", ")}.` });
    if (verifyDestination) {
      const destination = assertPublicUrl(requiredString(action, "destination_url", 8, 2_000));
      const source = await inspectSource(destination, claim);
      const verification = classifyClaim(claim, [source]);
      claimResult = { status: verification.verification_status, confidence: verification.confidence, source_urls: verification.evidence_source_urls, destination_checked: source.status === "checked" };
      if (source.status !== "checked") findings.push({ severity: "block", code: "destination_unreachable", message: "Destination evidence could not be checked." });
      else if (verification.verification_status === "contradicted") findings.push({ severity: "block", code: "claim_contradicted", message: "Advertisement claim conflicts with its destination evidence." });
      else if (verification.verification_status !== "supported") findings.push({ severity: "warn", code: "claim_not_supported", message: "Destination evidence does not sufficiently support the advertisement claim." });
    } else {
      claimResult = { status: "not_checked_in_free_preflight", destination_checked: false };
    }
  }

  const decision = findings.some((item) => item.severity === "block") ? "block" : findings.some((item) => item.severity === "warn") ? "manual_review" : "allow";
  const decisionBasis = {
    action_type: actionType,
    advertiser_id: advertiserId,
    claim_result: claimResult,
    finding_codes: findings.map((item) => item.code),
    destination_verification_performed: verifyDestination && actionType === "publish_ad",
  };
  const identity = await tiktokNotaryIdentity(action, authority, evidence, decisionBasis, decision);
  return {
    protocol: "capi2.tiktok_campaign_notary/1.0",
    billable: true,
    decision,
    risk_score: decision === "block" ? 100 : decision === "manual_review" ? 55 : 0,
    receipt_id: identity.receipt_id,
    integrity: { action_sha256: identity.action_sha256, authority_sha256: identity.authority_sha256, evidence_sha256: identity.evidence_sha256, decision_basis_sha256: identity.decision_basis_sha256 },
    action,
    authority,
    evidence,
    decision_basis: decisionBasis,
    findings,
    issued_at: new Date().toISOString(),
    limitations: ["Independent guardrail; not affiliated with or approved by TikTok.", "Not legal or platform-policy advice and does not execute any campaign action.", "Receipt proves payload integrity, not that TikTok accepted or executed the action."],
  };
}

async function verifyMilestone(criteria: Record<string, unknown>[], evidence: Record<string, unknown>[]) {
  const results = criteria.map((criterion) => {
    const id = requiredString(criterion, "id", 1, 120);
    const required = criterion.required !== false;
    const matches = evidence.filter((item) => optionalString(item.criterion_id) === id);
    const passed = matches.some((item) => item.status === "passed" && Boolean(optionalString(item.url) || optionalString(item.sha256)));
    return { id, required, passed, evidence_count: matches.length };
  });
  const failedRequired = results.filter((item) => item.required && !item.passed);
  const decision = failedRequired.length ? "fail" : "pass";
  return { protocol: "capi2.milestone_verifier/1.0", decision, criteria_passed: results.filter((item) => item.passed).length, criteria_failed: results.filter((item) => !item.passed).length, manual_review: evidence.some((item) => item.status === "manual_review"), results, criteria_sha256: await sha256Json(criteria), evidence_sha256: await sha256Json(evidence), limitations: ["Evidence presence and declared status are checked; referenced artifacts are not executed.", "A pass is decision support, not an instruction to release escrow."] };
}

async function inspectBacktest(report: Record<string, unknown>) {
  const findings: Array<{ severity: "warn" | "block"; code: string; message: string }> = [];
  const requiredFlags = [["transaction_costs_included", "missing_transaction_costs"], ["slippage_included", "missing_slippage"], ["survivorship_bias_controlled", "survivorship_bias_uncontrolled"], ["lookahead_bias_controlled", "lookahead_bias_uncontrolled"]] as const;
  for (const [field, code] of requiredFlags) if (report[field] !== true) findings.push({ severity: "block", code, message: `${field} must be explicitly true.` });
  if (!optionalString(report.out_of_sample_period)) findings.push({ severity: "block", code: "missing_out_of_sample", message: "No out-of-sample period is declared." });
  if (!optionalString(report.benchmark)) findings.push({ severity: "warn", code: "missing_benchmark", message: "No benchmark is declared." });
  if (!optionalString(report.dataset_hash) || !optionalString(report.code_hash)) findings.push({ severity: "warn", code: "not_reproducible", message: "Dataset and code hashes are required for reproducibility." });
  const tested = Number(report.strategies_tested ?? 1);
  if (Number.isFinite(tested) && tested > 20 && report.multiple_testing_correction !== true) findings.push({ severity: "warn", code: "multiple_testing_risk", message: `${tested} strategies were tested without an explicit multiple-testing correction.` });
  const decision = findings.some((item) => item.severity === "block") ? "block" : findings.length ? "manual_review" : "allow";
  return { protocol: "capi2.backtest_integrity/1.0", decision, risk_score: Math.min(100, findings.reduce((score, item) => score + (item.severity === "block" ? 30 : 12), 0)), simulation_only: true, findings, report_sha256: await sha256Json(report), limitations: ["This checks disclosed methodology, not market truth or future performance.", "Not investment advice and never an instruction to trade."] };
}

async function evaluatePaymentSafety(paymentRequired: Record<string, unknown>, policy: Record<string, unknown>) {
  const findings: Array<{ severity: "warn" | "block"; code: string; message: string }> = [];
  const accepts = Array.isArray(paymentRequired.accepts) ? paymentRequired.accepts.filter(isRecord) : [];
  const resource = isRecord(paymentRequired.resource) ? paymentRequired.resource : {};
  const resourceUrl = optionalString(resource.url);
  const maxAmountText = requiredString(policy, "max_amount_atomic", 1, 40);
  if (!/^\d+$/.test(maxAmountText)) throw new InputError("max_amount_atomic must be an unsigned integer string");
  const maxAmount = BigInt(maxAmountText);
  const allowedNetworks = stringArray(policy.allowed_networks, "allowed_networks");
  const allowedAssets = stringArray(policy.allowed_assets, "allowed_assets");
  const allowedRecipients = stringArray(policy.allowed_recipients, "allowed_recipients").map((value) => value.toLowerCase());

  if (paymentRequired.x402Version !== 2) findings.push({ severity: "block", code: "unsupported_x402_version", message: "Only x402 v2 is allowed." });
  if (!resourceUrl) findings.push({ severity: "block", code: "missing_resource_url", message: "Challenge has no resource URL." });
  else if ((policy.require_https ?? true) === true && !resourceUrl.startsWith("https://")) findings.push({ severity: "block", code: "resource_not_https", message: "Resource URL is not HTTPS." });
  if (accepts.length === 0) findings.push({ severity: "block", code: "no_payment_option", message: "Challenge has no payment option." });

  const evaluated = accepts.map((option) => {
    const amountText = optionalString(option.amount);
    const network = optionalString(option.network);
    const asset = optionalString(option.asset);
    const payTo = optionalString(option.payTo);
    const optionFindings: typeof findings = [];
    if (!amountText || !/^\d+$/.test(amountText)) optionFindings.push({ severity: "block", code: "invalid_amount", message: "Payment amount is not an unsigned integer." });
    else if (BigInt(amountText) > maxAmount) optionFindings.push({ severity: "block", code: "amount_above_limit", message: "Payment exceeds max_amount_atomic." });
    if (allowedNetworks.length && (!network || !allowedNetworks.includes(network))) optionFindings.push({ severity: "block", code: "network_not_allowed", message: "Payment network is not allowed by policy." });
    if (allowedAssets.length && (!asset || !allowedAssets.map((value) => value.toLowerCase()).includes(asset.toLowerCase()))) optionFindings.push({ severity: "block", code: "asset_not_allowed", message: "Payment asset is not allowed by policy." });
    if (!payTo || !/^0x[a-fA-F0-9]{40}$/.test(payTo)) optionFindings.push({ severity: "block", code: "invalid_recipient", message: "Recipient is not a valid EVM address." });
    else if (allowedRecipients.length && !allowedRecipients.includes(payTo.toLowerCase())) optionFindings.push({ severity: "block", code: "recipient_not_allowed", message: "Recipient is not allow-listed." });
    return { scheme: option.scheme ?? null, network, amount: amountText, asset, payTo, findings: optionFindings, allowed: optionFindings.every((finding) => finding.severity !== "block") };
  });
  const approvedOption = evaluated.find((option) => option.allowed) ?? null;
  findings.push(...(approvedOption ? approvedOption.findings : evaluated.flatMap((option) => option.findings)));
  if (!allowedRecipients.length) findings.push({ severity: "warn", code: "recipient_not_allowlisted", message: "Policy did not supply an allowed_recipients list." });
  const verdict = findings.some((finding) => finding.severity === "block") || !approvedOption ? "block" : findings.some((finding) => finding.severity === "warn") ? "warn" : "allow";
  return {
    protocol: "capi2.x402_buyer_guard/1.0",
    billable: true,
    verdict,
    risk_score: verdict === "block" ? 100 : verdict === "warn" ? 35 : 0,
    resource: resourceUrl,
    challenge_sha256: await sha256Json(paymentRequired),
    policy_sha256: await sha256Json(policy),
    approved_option: approvedOption,
    findings,
    options_evaluated: evaluated.length,
    limitations: ["This is a deterministic policy check, not recipient reputation or delivery-quality proof.", "The buyer must independently approve and sign any payment."],
  };
}

function stringArray(value: unknown, field: string): string[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || !item.trim())) throw new InputError(`${field} must be an array of strings`);
  return [...new Set(value.map((item) => (item as string).trim()))];
}

async function recordEvent(db: D1Database, event: CommerceEvent): Promise<void> {
  await db.prepare(`INSERT INTO commerce_events
    (event_id, occurred_at, request_id, route, event_type, payer_hash, transaction_hash, amount_atomic, network, estimated_cost_microusd, latency_ms, status_code, metadata_json)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
    .bind(event.event_id, event.occurred_at, event.request_id, event.route, event.event_type, event.payer_hash,
      event.transaction_hash, event.amount_atomic, event.network, event.estimated_cost_microusd, event.latency_ms, event.status_code, event.metadata_json)
    .run();
}

function decodeHeader(value: string | null): Record<string, unknown> | null {
  if (!value) return null;
  try {
    const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
    const decoded = atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "="));
    const parsed: unknown = JSON.parse(decoded);
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

async function readJson(request: Request): Promise<Record<string, unknown>> {
  const length = Number(request.headers.get("content-length") ?? "0");
  if (length > MAX_BODY_BYTES) throw new InputError("request body too large");
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > MAX_BODY_BYTES) throw new InputError("request body too large");
  try {
    const value: unknown = JSON.parse(text);
    return requireRecord(value, "body");
  } catch (error) {
    if (error instanceof InputError) throw error;
    throw new InputError("body must be valid JSON");
  }
}

function sourceUrls(input: Record<string, unknown>): string[] {
  const raw = Array.isArray(input.source_urls) ? input.source_urls : [input.vendor_url];
  if (raw.length < 1 || raw.length > MAX_SOURCES || raw.some((url) => typeof url !== "string")) {
    throw new InputError(`provide vendor_url or 1-${MAX_SOURCES} source_urls`);
  }
  return [...new Set(raw as string[])].map(assertPublicUrl);
}

function assertPublicUrl(value: string): string {
  let url: URL;
  try { url = new URL(value); } catch { throw new InputError("source URL is invalid"); }
  if (url.protocol !== "https:" || url.username || url.password || (url.port && url.port !== "443")) {
    throw new InputError("source URLs must use public HTTPS without credentials or custom ports");
  }
  const host = url.hostname.toLowerCase().replace(/[.]$/, "");
  if (host === "localhost" || host.endsWith(".local") || host.endsWith(".internal") || isPrivateIp(host)) {
    throw new InputError("source URL host is not public");
  }
  return url.toString();
}

function isPrivateIp(host: string): boolean {
  const ipv4 = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (ipv4) {
    const octets = ipv4.slice(1).map(Number);
    if (octets.some((part) => part > 255)) return true;
    const [a = 0, b = 0] = octets;
    return a === 0 || a === 10 || a === 127 || a >= 224 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
  }
  return host === "::1" || host.startsWith("fc") || host.startsWith("fd") || host.startsWith("fe8") || host.startsWith("fe9") || host.startsWith("fea") || host.startsWith("feb");
}

async function inspectSource(url: string, claim: string): Promise<SourceResult> {
  try {
    const response = await fetch(url, { headers: { "user-agent": "CAPI2-EvidenceBot/2.0", accept: "text/html,text/plain,application/json" }, redirect: "manual", signal: AbortSignal.timeout(8_000) });
    if (!response.ok) return { requested_url: url, final_url: url, status: "failed", text: "", error: `HTTP ${response.status}` };
    const length = Number(response.headers.get("content-length") ?? "0");
    if (length > MAX_SOURCE_BYTES) return { requested_url: url, final_url: url, status: "failed", text: "", error: "source too large" };
    const reader = response.body?.getReader();
    if (!reader) return { requested_url: url, final_url: url, status: "failed", text: "", error: "empty source" };
    const chunks: Uint8Array[] = [];
    let total = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_SOURCE_BYTES) { await reader.cancel(); throw new InputError("source too large"); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    const plain = new TextDecoder().decode(bytes)
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ")
      .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ")
      .replace(/<[^>]+>/g, " ").replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&").replace(/\s+/g, " ").trim();
    return { requested_url: url, final_url: response.url, status: "checked", text: bestSnippet(plain, claim) };
  } catch (error) {
    return { requested_url: url, final_url: url, status: "failed", text: "", error: error instanceof Error ? error.message : "fetch failed" };
  }
}

async function auditX402Route(url: string, method: string) {
  const started = Date.now();
  const response = await fetch(url, {
    method,
    headers: { "user-agent": "CAPI2-X402-Audit/1.0", accept: "application/json", ...(method === "POST" ? { "content-type": "application/json" } : {}) },
    body: method === "POST" ? "{}" : undefined,
    redirect: "manual",
    signal: AbortSignal.timeout(8_000),
  });
  const findings: Array<{ severity: "warn" | "block"; code: string; message: string }> = [];
  const header = response.headers.get("payment-required");
  const headerBytes = header ? new TextEncoder().encode(header).byteLength : 0;
  let challenge = decodeHeader(header);
  if (!challenge) {
    const body = (await response.text()).slice(0, 32_000);
    try { const parsed: unknown = JSON.parse(body); challenge = isRecord(parsed) ? parsed : null; } catch { challenge = null; }
  }
  if (response.status !== 402) findings.push({ severity: "block", code: "not_payment_required", message: `Expected HTTP 402 but received ${response.status}.` });
  if (!challenge) findings.push({ severity: "block", code: "challenge_unparseable", message: "No parseable PAYMENT-REQUIRED header or JSON challenge body." });
  const accepts = challenge && Array.isArray(challenge.accepts) ? challenge.accepts.filter(isRecord) : [];
  if (challenge && challenge.x402Version !== 2) findings.push({ severity: "block", code: "unsupported_version", message: "Challenge is not x402 v2." });
  if (challenge && accepts.length === 0) findings.push({ severity: "block", code: "missing_payment_options", message: "Challenge has no valid accepts options." });
  if (challenge && !isRecord(challenge.extensions)) findings.push({ severity: "warn", code: "missing_extensions", message: "Challenge exposes no discovery extensions." });
  else if (challenge && isRecord(challenge.extensions) && !isRecord(challenge.extensions.bazaar)) findings.push({ severity: "warn", code: "missing_bazaar", message: "Challenge has no Bazaar input/output schema." });
  if (!header) findings.push({ severity: "warn", code: "missing_payment_header", message: "Challenge exists only in the response body; v2 buyers expect PAYMENT-REQUIRED." });
  if (headerBytes > 12_000) findings.push({ severity: "warn", code: "large_payment_header", message: "PAYMENT-REQUIRED exceeds 12 KB and may be rejected by intermediaries." });
  for (const option of accepts) {
    if (!optionalString(option.amount) || !/^\d+$/.test(String(option.amount))) findings.push({ severity: "block", code: "invalid_atomic_amount", message: "An option does not use an atomic-unit integer amount." });
    if (!optionalString(option.network)?.includes(":")) findings.push({ severity: "block", code: "invalid_network", message: "An option lacks a CAIP-2 network identifier." });
    if (!optionalString(option.payTo)) findings.push({ severity: "block", code: "missing_recipient", message: "An option has no payment recipient." });
  }
  const verdict = findings.some((item) => item.severity === "block") ? "blocked" : findings.some((item) => item.severity === "warn") ? "degraded" : "ready";
  return {
    protocol: "capi2.x402_route_audit/1.0",
    verdict,
    url,
    method,
    status_code: response.status,
    latency_ms: Date.now() - started,
    x402_version: challenge?.x402Version ?? null,
    payment_options: accepts.length,
    payment_required_header_bytes: headerBytes,
    findings,
    challenge_sha256: challenge ? await sha256Json(challenge) : null,
    limitations: ["One unpaid probe only; no payment was signed, verified or settled.", "Compatibility indicators are not a guarantee of facilitator uptime or delivery quality."],
  };
}

async function extractPublicPage(url: string, query: string | null, maxChars: number) {
  const response = await fetch(url, {
    headers: { "user-agent": "CAPI2-WebExtract/1.0", accept: "text/html,text/plain,application/json" },
    redirect: "manual",
    signal: AbortSignal.timeout(8_000),
  });
  if (!response.ok) throw new InputError(`upstream returned HTTP ${response.status}`);
  const contentType = (response.headers.get("content-type") ?? "").split(";", 1)[0]?.trim().toLowerCase() ?? "";
  if (!contentType.startsWith("text/") && contentType !== "application/json") throw new InputError("upstream content type is not readable text or JSON");
  const declaredLength = Number(response.headers.get("content-length") ?? "0");
  if (declaredLength > MAX_SOURCE_BYTES) throw new InputError("source too large");
  const reader = response.body?.getReader();
  if (!reader) throw new InputError("upstream returned an empty body");
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_SOURCE_BYTES) { await reader.cancel(); throw new InputError("source too large"); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  const raw = new TextDecoder().decode(bytes);
  const title = contentType === "text/html" ? raw.match(/<title\b[^>]*>([\s\S]*?)<\/title>/i)?.[1]?.replace(/\s+/g, " ").trim() ?? null : null;
  const readable = contentType === "text/html"
    ? raw.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, " ").replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, " ").replace(/<[^>]+>/g, " ")
    : raw;
  const normalized = readable.replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&").replace(/&lt;/gi, "<").replace(/&gt;/gi, ">").replace(/\s+/g, " ").trim();
  const selected = query ? relevantText(normalized, query, maxChars) : normalized.slice(0, maxChars);
  return {
    protocol: "capi2.web_extract/1.0",
    requested_url: url,
    final_url: response.url,
    content_type: contentType,
    title,
    query,
    text: selected,
    content_sha256: await sha256Text(raw),
    source_bytes: total,
    returned_chars: selected.length,
    truncated: selected.length < normalized.length,
    fetched_at: new Date().toISOString(),
    limitations: ["Public HTTPS only; redirects, credentials, custom headers, scripts and binary content are not supported.", "Returned text is source material, not a truth or copyright certification."],
  };
}

function relevantText(text: string, query: string, maxChars: number): string {
  const terms = keywords(query);
  const blocks = text.split(/(?<=[.!?])\s+/).filter((block) => block.length >= 20);
  return blocks.map((block, index) => ({ block, index, score: terms.filter((term) => block.toLowerCase().includes(term)).length }))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map(({ block }) => block)
    .join(" ")
    .slice(0, maxChars);
}

function classifyClaim(claim: string, sources: SourceResult[]) {
  const tokens = keywords(claim);
  const checked = sources.filter((source) => source.status === "checked");
  const evidence = checked.map((source) => {
    const lower = source.text.toLowerCase();
    const overlap = tokens.filter((token) => lower.includes(token)).length;
    const score = tokens.length ? overlap / tokens.length : 0;
    const contradicted = score >= 0.45 && /\b(no|not|never|without|cannot|doesn't|does not)\b/i.test(source.text);
    return { text: source.text, score: Number(score.toFixed(3)), source_url: source.final_url, contradicted };
  }).sort((a, b) => b.score - a.score);
  const top = evidence[0];
  const status = top?.contradicted ? "contradicted" : (top?.score ?? 0) >= 0.55 ? "supported" : "uncertain";
  return {
    protocol: PROTOCOL,
    claim,
    verification_status: status,
    verification_result: status,
    verdict: status === "supported" ? "SUPPORTED_BY_SUPPLIED_SOURCE" : status === "contradicted" ? "CONTRADICTED_BY_SUPPLIED_SOURCE" : "INSUFFICIENT_PUBLIC_EVIDENCE",
    confidence: Number(Math.min(0.95, Math.max(0.25, top?.score ?? 0.25)).toFixed(3)),
    evidence_summary: top?.text ?? "No supplied source could be checked.",
    evidence_source_urls: evidence.map((item) => item.source_url),
    evidence: evidence.map(({ contradicted: _contradicted, ...item }) => item),
    caveats: ["Checks only buyer-supplied public URLs.", "Keyword evidence scoring is not certification or legal advice."],
    request_id: `cv_${crypto.randomUUID().replaceAll("-", "")}`,
    checked_at: new Date().toISOString(),
    sources_checked: checked.length,
    source_results: sources.map(({ text: _text, ...source }) => source),
  };
}

function bestSnippet(text: string, claim: string): string {
  const terms = keywords(claim);
  const sentences = text.split(/(?<=[.!?])\s+/).filter((sentence) => sentence.length >= 20 && sentence.length <= 700);
  const ranked = sentences.map((sentence) => ({ sentence, score: terms.filter((term) => sentence.toLowerCase().includes(term)).length })).sort((a, b) => b.score - a.score);
  return (ranked[0]?.sentence ?? text.slice(0, 700)).slice(0, 700);
}

function keywords(value: string): string[] {
  const stop = new Set(["about", "against", "claim", "claims", "states", "that", "their", "there", "these", "this", "vendor", "with", "from", "have"]);
  return [...new Set(value.toLowerCase().match(/[a-z0-9]{3,}/g) ?? [])].filter((token) => !stop.has(token));
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  return `{${Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(",")}}`;
}

async function sha256Json(value: unknown): Promise<string> { return sha256Text(canonicalJson(value)); }
async function sha256Text(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function withPostMethod(extension: Record<string, unknown>): Record<string, unknown> {
  const copy = structuredClone(extension);
  const bazaar = copy.bazaar;
  if (isRecord(bazaar) && isRecord(bazaar.info) && isRecord(bazaar.info.input)) {
    bazaar.info.input.method = "POST";
  }
  return copy;
}
function requireRecord(value: unknown, name: string): Record<string, unknown> { if (!isRecord(value)) throw new InputError(`${name} must be an object`); return value; }
function optionalString(value: unknown): string | null { return typeof value === "string" && value.trim() ? value.trim() : null; }
function requiredString(input: Record<string, unknown>, field: string, min: number, max: number): string {
  const value = optionalString(input[field]);
  if (!value || value.length < min || value.length > max) throw new InputError(`${field} must contain ${min}-${max} characters`);
  return value;
}

function openApi(origin: string) {
  const paths: Record<string, Record<string, unknown>> = Object.fromEntries(PRODUCTS.map((product) => [product.path, {
    [product.method.toLowerCase()]: {
      summary: product.buyer_job,
      security: [{ x402Payment: [] }],
      "x-payment-info": {
        protocols: ["x402"],
        price: { mode: "fixed", currency: "USD", amount: product.price_usd.toFixed(2) },
        network: "eip155:8453",
      },
      responses: {
        "200": { description: "Paid delivery" },
        "402": { description: "x402 payment required" },
      },
    },
  }]));
  paths["/v1/commerce-receipts/verify"] = {
    post: { summary: "Verify receipt payload integrity for free.", security: [], responses: { "200": { description: "Integrity result" } } },
  };
  paths["/v1/quote"] = {
    get: { summary: "Get exact payment terms for a product for free.", security: [], responses: { "200": { description: "Exact x402 quote" }, "404": { description: "Unknown product" } } },
  };
  paths["/v1/preflight"] = {
    post: { summary: "Validate a product payload before payment for free.", security: [], responses: { "200": { description: "Valid payload and exact payment terms" }, "422": { description: "Invalid payload" } } },
  };
  paths["/v1/web-extract/demo"] = {
    get: { summary: "Inspect a cached free example of the web extraction delivery format.", security: [], responses: { "200": { description: "Free non-billable demo delivery" } } },
  };
  paths["/v1/action-guard/demo"] = {
    get: { summary: "Inspect a free example showing a wrong quote and unavailable slot being blocked.", security: [], responses: { "200": { description: "Free non-billable action guard demo" } } },
  };
  paths["/v1/action-notary/demo"] = {
    get: { summary: "Inspect a free blocked-action notary receipt.", security: [], responses: { "200": { description: "Free non-billable notary demo" } } },
  };
  paths["/v1/action-notary/verify"] = {
    post: { summary: "Verify an action-notary receipt for free.", security: [], responses: { "200": { description: "Receipt integrity result" } } },
  };
  paths["/v1/tiktok-ad-preflight"] = {
    post: { summary: "Check TikTok campaign authority and spending rules for free without executing an action.", security: [], responses: { "200": { description: "Free non-billable risk preview" }, "422": { description: "Invalid payload" } } },
  };
  paths["/v1/tiktok-campaign-notary/demo"] = {
    get: { summary: "Inspect a free example where an unauthorized TikTok budget increase is blocked.", security: [], responses: { "200": { description: "Free non-billable campaign notary demo" } } },
  };
  paths["/v1/tiktok-campaign-notary/verify"] = {
    post: { summary: "Verify a TikTok campaign-notary receipt for free.", security: [], responses: { "200": { description: "Receipt integrity result" } } },
  };
  return {
    openapi: "3.1.0",
    info: {
      title: "CAPI2 Agent Commerce",
      version: SERVICE_VERSION,
      description: "Programmable authority checks and tamper-evident receipts for autonomous agents, sold through sustainable x402 commerce.",
      contact: { url: `${origin}/health` },
      "x-guidance": "Call the free discovery endpoints first. Paid POST routes return an x402 v2 challenge; only retry with PAYMENT-SIGNATURE after the buyer approves the exact amount, asset, network, recipient, and resource.",
    },
    servers: [{ url: origin }],
    components: { securitySchemes: { x402Payment: { type: "apiKey", in: "header", name: "PAYMENT-SIGNATURE", description: "x402 v2 payment authorization" } } },
    paths,
  };
}
