#!/usr/bin/env node

// PayanAgent catalog endpoint health checker. Uses only unpaid OPTIONS probes.
const baseUrl = process.env.PAYAN_BASE_URL || "https://payanagent.com";
const requestedLimit = Number.parseInt(process.env.PAYAN_OFFER_LIMIT || "100", 10);
const limit = Number.isFinite(requestedLimit) ? Math.max(1, requestedLimit) : 100;
const timeoutMs = Number.parseInt(process.env.PAYAN_PROBE_TIMEOUT_MS || "5000", 10);
const concurrency = Number.parseInt(process.env.PAYAN_PROBE_CONCURRENCY || "12", 10);

async function fetchOffers() {
  const offers = [];
  let cursor;
  while (offers.length < limit) {
    const url = new URL("/api/v1/offers", baseUrl);
    url.searchParams.set("sort", "top");
    url.searchParams.set("limit", String(Math.min(100, limit - offers.length)));
    if (cursor) url.searchParams.set("cursor", cursor);
    const response = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
    if (!response.ok) throw new Error(`catalog returned HTTP ${response.status}`);
    const page = await response.json();
    const rows = Array.isArray(page.offers) ? page.offers : [];
    offers.push(...rows);
    cursor = page.nextCursor;
    if (!cursor || rows.length === 0) break;
  }
  return offers.slice(0, limit);
}

function classify(code) {
  if (code >= 500) return "5xx";
  if (code >= 400 && code !== 402) return "4xx";
  return "alive";
}

async function probe(offer) {
  const offerId = offer._id || offer.id || null;
  const endpoint = new URL(offer.buyUrl || `/x402/${offerId}`, baseUrl).href;
  const started = performance.now();
  try {
    const response = await fetch(endpoint, {
      method: "OPTIONS",
      redirect: "follow",
      signal: AbortSignal.timeout(timeoutMs),
    });
    return { offerId, title: offer.title || null, endpoint, status: classify(response.status), httpCode: response.status, latencyMs: Math.round(performance.now() - started) };
  } catch (error) {
    const timedOut = error?.name === "TimeoutError" || error?.name === "AbortError";
    return { offerId, title: offer.title || null, endpoint, status: timedOut ? "timeout" : "dead", httpCode: null, latencyMs: Math.round(performance.now() - started) };
  }
}

async function mapConcurrent(items, worker, width) {
  const output = new Array(items.length);
  let next = 0;
  async function run() {
    while (next < items.length) {
      const index = next++;
      output[index] = await worker(items[index]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(width, items.length) }, run));
  return output;
}

const offers = await fetchOffers();
const results = await mapConcurrent(offers, probe, Math.max(1, concurrency));
process.stdout.write(`${JSON.stringify(results, null, 2)}\n`);

const unhealthy = results.filter(({ status }) => status !== "alive");
const lines = ["# PayanAgent catalog endpoint health report", "", `Checked ${results.length} offers using unpaid OPTIONS requests; ${unhealthy.length} require review.`, ""];
if (unhealthy.length === 0) lines.push("No dead or unhealthy endpoints found.");
else {
  lines.push("| Offer | Status | HTTP | Latency |", "|---|---:|---:|---:|");
  for (const row of unhealthy) lines.push(`| ${row.title || row.offerId} | ${row.status} | ${row.httpCode ?? "—"} | ${row.latencyMs} ms |`);
}
process.stderr.write(`${lines.join("\n")}\n`);
