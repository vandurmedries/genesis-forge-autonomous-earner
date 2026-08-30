const DEFAULT_ORIGIN = "https://capi2-agent-marketplace-router.onrender.com";

export class AckMintClient {
  constructor({ integrationToken = null, origin = DEFAULT_ORIGIN, fetchImpl = fetch } = {}) {
    this.integrationToken = integrationToken;
    this.origin = origin.replace(/\/$/, "");
    this.fetchImpl = fetchImpl;
    if (!this.origin.startsWith("https://")) throw new Error("AckMint origin must use HTTPS");
  }

  async #json(path, options = {}) {
    const response = await this.fetchImpl(`${this.origin}${path}`, {
      ...options,
      headers: { "content-type": "application/json", ...(options.headers || {}) },
    });
    const text = await response.text();
    let body;
    try { body = text ? JSON.parse(text) : null; } catch { body = { raw: text }; }
    if (!response.ok) {
      const error = new Error(`AckMint HTTP ${response.status}`);
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return { body, paymentResponse: response.headers.get("Payment-Response") };
  }

  async challenge({ callbackUrl, serviceName, integrationTtlDays = 365 }) {
    const { body } = await this.#json("/v1/ackmint/integrations/challenge", {
      method: "POST",
      body: JSON.stringify({
        callback_url: callbackUrl,
        service_name: serviceName,
        integration_ttl_days: integrationTtlDays,
      }),
    });
    return body;
  }

  async verifyIntegration(challengeToken) {
    const { body } = await this.#json("/v1/ackmint/integrations/verify", {
      method: "POST",
      body: JSON.stringify({ challenge_token: challengeToken }),
    });
    if (typeof body?.integration_token === "string") this.integrationToken = body.integration_token;
    return body;
  }

  async emit({ eventId, eventType, payload, tier = "standard", source = "urn:capi2:external", idempotencyKey = null }) {
    if (!["standard", "assured", "critical"].includes(tier)) throw new Error("Invalid AckMint tier");
    if (!this.integrationToken) throw new Error("integrationToken is required");
    const request = {
      integration_token: this.integrationToken,
      event_id: eventId,
      event_type: eventType,
      source,
      payload,
    };
    if (idempotencyKey) request.idempotency_key = idempotencyKey;
    return this.#json(`/v1/ackmint/relay/${tier}`, {
      method: "POST",
      body: JSON.stringify(request),
    });
  }

  async status({ eventId, idempotencyKey = null }) {
    if (!this.integrationToken) throw new Error("integrationToken is required");
    const request = { integration_token: this.integrationToken, event_id: eventId };
    if (idempotencyKey) request.idempotency_key = idempotencyKey;
    const { body } = await this.#json("/v1/ackmint/relay/status", {
      method: "POST",
      body: JSON.stringify(request),
    });
    return body;
  }
}

// For paid calls, pass an x402-enabled fetch implementation as `fetchImpl`.
// A normal fetch remains useful for onboarding and will receive HTTP 402 on paid routes.
