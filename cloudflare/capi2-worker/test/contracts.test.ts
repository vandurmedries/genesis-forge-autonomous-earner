import { describe, expect, it } from "vitest";
import worker from "../src/index";

const testEnv = {
  ENVIRONMENT: "test",
  PUBLIC_ORIGIN: "https://example.test",
  PAY_TO: "0x4B4031bd3B334e010E6ecE66d14DEa59eB34122a",
  NETWORK: "eip155:8453",
  FACILITATOR_URL: "https://facilitator.payai.network",
  MIN_MARGIN_BPS: "7000",
};

describe("CAPI2 Worker contracts", () => {
  it("publishes health and sustainable pricing", async () => {
    const response = await worker.fetch(new Request("https://example.test/health"), testEnv as Env, {} as ExecutionContext);
    expect(response.status).toBe(200);
    const body = await response.json<Record<string, unknown>>();
    expect(body.runtime).toBe("cloudflare-workers");
    expect(body.network).toBe("eip155:8453");
  });

  it("publishes all paid resources", async () => {
    const response = await worker.fetch(new Request("https://example.test/v1/buyer-catalog"), testEnv as Env, {} as ExecutionContext);
    const body = await response.json<{ resources: Array<{ price_usd: number }> }>();
    expect(body.resources.map((item) => item.price_usd)).toEqual([0.008, 0.015, 0.005, 0.005, 0.1, 0.25, 0.01, 0.02, 0.15, 0.2, 0.12]);
  });

  it("focuses the landing response and publishes agent purchase instructions", async () => {
    const landing = await worker.fetch(new Request("https://example.test/"), testEnv as Env, {} as ExecutionContext);
    const landingBody = await landing.json<{ recommended_product: { id: string; free_demo: string } }>();
    expect(landingBody.recommended_product.id).toBe("voice_booking_action_guard");
    expect(landingBody.recommended_product.free_demo).toContain("/v1/action-guard/demo");
    const instructions = await worker.fetch(new Request("https://example.test/llms.txt"), testEnv as Env, {} as ExecutionContext);
    expect(await instructions.text()).toContain("Safe purchase sequence");
  });

  it("quotes every product with an exact approval scope", async () => {
    const response = await worker.fetch(new Request("https://example.test/v1/quote?product_id=vendor_risk_pack"), testEnv as Env, {} as ExecutionContext);
    const body = await response.json<{ amount: string; resource: string; approval_scope: string[] }>();
    expect(response.status).toBe(200);
    expect(body.amount).toBe("250000");
    expect(body.resource).toBe("https://example.test/v1/vendor-risk-pack");
    expect(body.approval_scope).toEqual(["amount", "asset", "network", "recipient", "resource"]);
  });

  it("preflights a valid payload without charging", async () => {
    const response = await worker.fetch(new Request("https://example.test/v1/preflight", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ product_id: "claim_verify", payload: { claim: "Workers run globally", source_urls: ["https://developers.cloudflare.com/workers/"] } }),
    }), testEnv as Env, {} as ExecutionContext);
    const body = await response.json<{ valid: boolean; billable: boolean; exact_payment: { amount: string } }>();
    expect(response.status).toBe(200);
    expect(body.valid).toBe(true);
    expect(body.billable).toBe(false);
    expect(body.exact_payment.amount).toBe("100000");
  });

  it("rejects invalid preflight payloads before payment", async () => {
    const response = await worker.fetch(new Request("https://example.test/v1/preflight", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ product_id: "claim_verify", payload: { claim: "x" } }),
    }), testEnv as Env, {} as ExecutionContext);
    expect(response.status).toBe(422);
  });

  it("preflights the x402 buyer guard at half a cent", async () => {
    const response = await worker.fetch(new Request("https://example.test/v1/preflight", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        product_id: "x402_buyer_guard",
        payload: {
          payment_required: { x402Version: 2, resource: { url: "https://seller.example/data" }, accepts: [] },
          policy: { max_amount_atomic: "10000", allowed_networks: ["eip155:8453"] },
        },
      }),
    }), testEnv as Env, {} as ExecutionContext);
    const body = await response.json<{ valid: boolean; exact_payment: { amount: string } }>();
    expect(response.status).toBe(200);
    expect(body.valid).toBe(true);
    expect(body.exact_payment.amount).toBe("5000");
  });

  it("preflights the public web extractor at half a cent", async () => {
    const response = await worker.fetch(new Request("https://example.test/v1/preflight", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ product_id: "agent_web_extract", payload: { url: "https://example.com/", query: "domain facts", max_chars: 4000 } }),
    }), testEnv as Env, {} as ExecutionContext);
    const body = await response.json<{ valid: boolean; exact_payment: { amount: string } }>();
    expect(response.status).toBe(200);
    expect(body.valid).toBe(true);
    expect(body.exact_payment.amount).toBe("5000");
  });

  it("preflights the x402 route audit and grounding pack", async () => {
    const payloads = [
      { product_id: "x402_route_audit", payload: { url: "https://seller.example/paid", method: "POST" }, amount: "8000" },
      { product_id: "multi_source_grounding", payload: { query: "security controls", source_urls: ["https://example.com/security"] }, amount: "15000" },
    ];
    for (const item of payloads) {
      const response = await worker.fetch(new Request("https://example.test/v1/preflight", {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(item),
      }), testEnv as Env, {} as ExecutionContext);
      const body = await response.json<{ valid: boolean; exact_payment: { amount: string } }>();
      expect(response.status).toBe(200);
      expect(body.valid).toBe(true);
      expect(body.exact_payment.amount).toBe(item.amount);
    }
  });

  it("preflights the four action-critical products", async () => {
    const payloads = [
      { product_id: "voice_booking_action_guard", payload: { proposed_action: { service_id: "visit", quoted_price: 79 }, authority: { services: [{ id: "visit", price: 129 }] } }, amount: "20000" },
      { product_id: "milestone_verifier", payload: { criteria: [{ id: "health" }], evidence: [] }, amount: "150000" },
      { product_id: "backtest_integrity_guard", payload: { report: { strategies_tested: 1 } }, amount: "200000" },
      { product_id: "ad_claim_destination_guard", payload: { destination_url: "https://example.com/", claim: "Example Domain" }, amount: "120000" },
    ];
    for (const item of payloads) {
      const response = await worker.fetch(new Request("https://example.test/v1/preflight", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(item) }), testEnv as Env, {} as ExecutionContext);
      const body = await response.json<{ valid: boolean; exact_payment: { amount: string } }>();
      expect(response.status).toBe(200);
      expect(body.valid).toBe(true);
      expect(body.exact_payment.amount).toBe(item.amount);
    }
  });

  it("blocks a wrong quote and unavailable slot in the free demo", async () => {
    const response = await worker.fetch(new Request("https://example.test/v1/action-guard/demo"), testEnv as Env, {} as ExecutionContext);
    const body = await response.json<{ decision: string; billable: boolean; findings: Array<{ code: string }> }>();
    expect(response.status).toBe(200);
    expect(body.billable).toBe(false);
    expect(body.decision).toBe("block");
    expect(body.findings.map((item) => item.code)).toEqual(["price_mismatch", "slot_unavailable"]);
  });
});
