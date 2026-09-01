import { env } from "cloudflare:workers";
import { HTTPFacilitatorClient } from "@x402/core/server";
import { ExactEvmScheme } from "@x402/evm/exact/server";
import { paymentMiddleware, x402ResourceServer } from "@x402/hono";
import { Hono } from "hono";
import { cors } from "hono/cors";

const SERVICE_VERSION = "2.0.0";
const PROTOCOL = `capi2.claim_verify/${SERVICE_VERSION}`;
const USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const MAX_BODY_BYTES = 24_000;
const MAX_SOURCE_BYTES = 160_000;
const MAX_SOURCES = 3;

const PRICES = {
  claimVerify: { display: "$0.10", atomic: 100_000, costCeilingMicrousd: 20_000 },
  riskPack: { display: "$0.25", atomic: 250_000, costCeilingMicrousd: 50_000 },
  receiptIssue: { display: "$0.01", atomic: 10_000, costCeilingMicrousd: 1_000 },
} as const;

const PRODUCTS = [
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
] as const;

const workerEnv = env;
const facilitator = new HTTPFacilitatorClient({ url: workerEnv.FACILITATOR_URL });
const resourceServer = new x402ResourceServer(facilitator).register(
  workerEnv.NETWORK,
  new ExactEvmScheme(),
);

resourceServer.onAfterSettle(async ({ result, requirements }) => {
  console.log(JSON.stringify({
    event: "x402_settled",
    success: result.success,
    transaction: result.transaction,
    network: result.network,
    amount: requirements.amount,
  }));
});

const paidRoutes = {
  "POST /v1/claim-verify": {
    accepts: {
      scheme: "exact",
      price: PRICES.claimVerify.display,
      network: workerEnv.NETWORK,
      payTo: workerEnv.PAY_TO,
    },
    description: "Evidence-backed verification of one public vendor or product claim.",
    mimeType: "application/json",
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
  },
};

const app = new Hono<{ Bindings: Env }>();
let x402Middleware: ReturnType<typeof paymentMiddleware> | undefined;

app.use("*", cors({ origin: "*", allowMethods: ["GET", "POST", "OPTIONS"], exposeHeaders: ["PAYMENT-REQUIRED", "PAYMENT-RESPONSE"] }));
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
    metadata_json: JSON.stringify({ monitor: c.req.header("x-capi2-monitor") === "true" }),
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
  promise: "Verifiable commerce for autonomous agents.",
  version: SERVICE_VERSION,
  health: `${c.env.PUBLIC_ORIGIN}/health`,
  discovery: `${c.env.PUBLIC_ORIGIN}/.well-known/x402`,
  catalog: `${c.env.PUBLIC_ORIGIN}/v1/buyer-catalog`,
}));

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
  x402Version: 2,
  service: "CAPI2 Agent Commerce",
  network: c.env.NETWORK,
  asset: USDC,
  payTo: c.env.PAY_TO,
  resources: PRODUCTS.map((product) => ({
    ...product,
    resource: `${c.env.PUBLIC_ORIGIN}${product.path}`,
  })),
}));

app.get("/v1/buyer-catalog", (c) => c.json({
  protocol: "capi2.buyer_catalog/2.0",
  settlement: { network: c.env.NETWORK, asset: "USDC", recipient: c.env.PAY_TO },
  margin_policy: { minimum_gross_margin_bps: Number(c.env.MIN_MARGIN_BPS), revenue_basis: "settled external payments only" },
  resources: PRODUCTS,
}));

app.get("/v1/verifiable-commerce", (c) => c.json({
  protocol: "capi2.verifiable_commerce/1.0",
  promise: "Verifiable commerce for autonomous agents.",
  products: PRODUCTS,
  evidence_policy: [
    "Settlement proves payment finality, not delivery quality.",
    "Receipts bind payload integrity; they do not certify truth.",
    "Revenue reporting counts only settled, successfully delivered requests.",
  ],
}));

app.get("/v1/quote", (c) => c.json({
  protocol: "capi2.quote/2.0",
  resource: `${c.env.PUBLIC_ORIGIN}/v1/claim-verify`,
  price: PRICES.claimVerify.display,
  amount: String(PRICES.claimVerify.atomic),
  asset: "USDC",
  asset_address: USDC,
  network: c.env.NETWORK,
  recipient: c.env.PAY_TO,
  scheme: "exact",
  x402_version: 2,
}));

app.get("/v1/free-x402-market-radar", (c) => c.json({
  protocol: "capi2.market_radar/2.0",
  billable: false,
  external_payments_made: false,
  query: c.req.query("q") ?? "agent verification",
  offers: PRODUCTS,
  capi2_positioning: { price_usd: PRICES.claimVerify.atomic / 1_000_000, network: c.env.NETWORK },
}));

app.post("/v1/claim-verify/dry-run", async (c) => {
  const input = await readJson(c.req.raw);
  const claim = requiredString(input, "claim", 3, 1_200);
  const evidenceText = requiredString(input, "evidence_text", 3, 8_000);
  return c.json({ ...classifyClaim(claim, [{ requested_url: "inline:evidence", final_url: "inline:evidence", status: "checked", text: bestSnippet(evidenceText, claim) }]), billable: false });
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
  if (route === "/v1/claim-verify") return PRICES.claimVerify;
  if (route === "/v1/vendor-risk-pack") return PRICES.riskPack;
  if (route === "/v1/commerce-receipts/issue") return PRICES.receiptIssue;
  return null;
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
    const response = await fetch(url, { headers: { "user-agent": "CAPI2-EvidenceBot/2.0", accept: "text/html,text/plain,application/json" }, redirect: "error", signal: AbortSignal.timeout(8_000) });
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
function requireRecord(value: unknown, name: string): Record<string, unknown> { if (!isRecord(value)) throw new InputError(`${name} must be an object`); return value; }
function optionalString(value: unknown): string | null { return typeof value === "string" && value.trim() ? value.trim() : null; }
function requiredString(input: Record<string, unknown>, field: string, min: number, max: number): string {
  const value = optionalString(input[field]);
  if (!value || value.length < min || value.length > max) throw new InputError(`${field} must contain ${min}-${max} characters`);
  return value;
}

function openApi(origin: string) {
  return {
    openapi: "3.1.0",
    info: { title: "CAPI2 Agent Commerce", version: SERVICE_VERSION, description: "Sustainable x402 commerce with evidence and verifiable receipts." },
    servers: [{ url: origin }],
    paths: Object.fromEntries(PRODUCTS.map((product) => [product.path, { [product.method.toLowerCase()]: { summary: product.buyer_job, responses: { "200": { description: "Paid delivery" }, "402": { description: "x402 payment required" } } } }])),
  };
}
