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

  it("publishes three paid resources", async () => {
    const response = await worker.fetch(new Request("https://example.test/v1/buyer-catalog"), testEnv as Env, {} as ExecutionContext);
    const body = await response.json<{ resources: Array<{ price_usd: number }> }>();
    expect(body.resources.map((item) => item.price_usd)).toEqual([0.1, 0.25, 0.01]);
  });
});
