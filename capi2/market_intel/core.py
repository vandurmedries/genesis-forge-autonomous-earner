from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse


# The demand priors below are explicit product assumptions, not observed demand.
# They make the scoring model auditable instead of hiding subjective judgment.
TAXONOMY: tuple[dict[str, Any], ...] = (
    {
        "slug": "compliance_due_diligence",
        "label": "Compliance & due diligence",
        "concept_name": "ProofRoute",
        "keywords": ["compliance", "kyb", "kyc", "sanctions", "due diligence", "aml", "adverse media", "vendor risk"],
        "demand_prior": 0.96,
        "default_price_usd": 0.05,
        "build_difficulty": "medium",
        "target_buyer": "procurement, fintech and B2B marketplace agents",
        "promise": "Turn a company, domain or claim into a compact evidence-backed risk packet.",
        "path": "/v1/company-proof",
        "input_example": {"company": "Example BV", "domain": "example.com", "jurisdiction": "BE"},
        "output_example": {"risk_flags": [], "evidence": [], "confidence": 0.0},
        "tags": ["compliance", "due-diligence", "evidence"],
    },
    {
        "slug": "developer_code_quality",
        "label": "Developer & code quality",
        "concept_name": "PatchProof",
        "keywords": ["code", "repository", "github", "dependency", "package", "npm", "audit", "pull request", "software"],
        "demand_prior": 0.92,
        "default_price_usd": 0.02,
        "build_difficulty": "medium",
        "target_buyer": "coding agents, maintainers and software teams",
        "promise": "Score a repository change for breakage, dependency and maintenance risk before merge.",
        "path": "/v1/patch-risk",
        "input_example": {"repository": "owner/repo", "diff": "@@ ..."},
        "output_example": {"risk_score": 0, "findings": [], "recommended_tests": []},
        "tags": ["developer-tools", "code-review", "risk"],
    },
    {
        "slug": "commerce_price_intelligence",
        "label": "Commerce & price intelligence",
        "concept_name": "MarginScout",
        "keywords": ["price", "product", "shopping", "commerce", "ecommerce", "marketplace", "retail", "deal", "inventory"],
        "demand_prior": 0.94,
        "default_price_usd": 0.01,
        "build_difficulty": "medium",
        "target_buyer": "reseller, procurement and shopping agents",
        "promise": "Compare a product across sellers and return a margin-ready purchase decision.",
        "path": "/v1/margin-scout",
        "input_example": {"query": "product or SKU", "country": "BE", "minimum_margin_pct": 20},
        "output_example": {"offers": [], "best_route": None, "estimated_margin_pct": None},
        "tags": ["commerce", "pricing", "procurement"],
    },
    {
        "slug": "identity_reputation",
        "label": "Identity & reputation",
        "concept_name": "AgentCred",
        "keywords": ["identity", "reputation", "trust", "wallet", "credential", "attestation", "profile", "verification"],
        "demand_prior": 0.91,
        "default_price_usd": 0.03,
        "build_difficulty": "hard",
        "target_buyer": "agent marketplaces and autonomous buyers",
        "promise": "Produce a portable trust summary from receipts, attestations and public operating history.",
        "path": "/v1/reputation-summary",
        "input_example": {"subject": "did:web:agent.example", "evidence_urls": []},
        "output_example": {"trust_score": 0, "signals": [], "warnings": []},
        "tags": ["identity", "reputation", "agents"],
    },
    {
        "slug": "cybersecurity_threat_intel",
        "label": "Cybersecurity & threat intelligence",
        "concept_name": "ThreatSlice",
        "keywords": ["security", "cyber", "threat", "malware", "phishing", "cve", "vulnerability", "domain reputation", "ip reputation"],
        "demand_prior": 0.95,
        "default_price_usd": 0.03,
        "build_difficulty": "medium",
        "target_buyer": "security agents, SOC tooling and browser agents",
        "promise": "Convert a URL, IP, package or CVE into a decision-sized threat slice.",
        "path": "/v1/threat-slice",
        "input_example": {"indicator": "example.com", "indicator_type": "domain"},
        "output_example": {"verdict": "unknown", "signals": [], "recommended_action": "review"},
        "tags": ["security", "threat-intel", "reputation"],
    },
    {
        "slug": "onchain_risk_data",
        "label": "Onchain risk & transaction data",
        "concept_name": "ChainContext",
        "keywords": ["blockchain", "onchain", "transaction", "token", "wallet", "defi", "contract", "solana", "ethereum", "base"],
        "demand_prior": 0.88,
        "default_price_usd": 0.02,
        "build_difficulty": "medium",
        "target_buyer": "wallet, trading and treasury agents",
        "promise": "Explain an address, token or transaction with risk flags and plain-language context.",
        "path": "/v1/chain-context",
        "input_example": {"network": "eip155:8453", "address_or_tx": "0x..."},
        "output_example": {"summary": "", "risk_flags": [], "evidence": []},
        "tags": ["onchain", "risk", "wallet"],
    },
    {
        "slug": "document_extraction",
        "label": "Document extraction & transformation",
        "concept_name": "DocToAction",
        "keywords": ["pdf", "document", "ocr", "extract", "markdown", "invoice", "receipt", "contract", "parse"],
        "demand_prior": 0.89,
        "default_price_usd": 0.01,
        "build_difficulty": "easy",
        "target_buyer": "workflow agents and operations teams",
        "promise": "Extract only the fields and actions an agent needs from a document.",
        "path": "/v1/document-actions",
        "input_example": {"url": "https://example.com/document.pdf", "requested_fields": []},
        "output_example": {"fields": {}, "actions": [], "citations": []},
        "tags": ["documents", "extraction", "workflow"],
    },
    {
        "slug": "legal_policy_intelligence",
        "label": "Legal & policy intelligence",
        "concept_name": "ClauseSignal",
        "keywords": ["legal", "law", "policy", "terms", "contract", "regulation", "clause", "privacy", "gdpr"],
        "demand_prior": 0.90,
        "default_price_usd": 0.05,
        "build_difficulty": "hard",
        "target_buyer": "contract, procurement and compliance agents",
        "promise": "Detect operationally important clauses and policy changes without pretending to give legal advice.",
        "path": "/v1/clause-signal",
        "input_example": {"text_or_url": "https://example.com/terms", "focus": ["termination", "data use"]},
        "output_example": {"signals": [], "citations": [], "needs_human_review": True},
        "tags": ["legal-ops", "policy", "contracts"],
    },
    {
        "slug": "logistics_shipping",
        "label": "Logistics & shipping",
        "concept_name": "RouteReady",
        "keywords": ["shipping", "logistics", "freight", "port", "vessel", "carrier", "route", "delivery", "customs"],
        "demand_prior": 0.90,
        "default_price_usd": 0.02,
        "build_difficulty": "medium",
        "target_buyer": "procurement, freight and supply-chain agents",
        "promise": "Turn route and shipment inputs into delay, cost and documentation signals.",
        "path": "/v1/route-readiness",
        "input_example": {"origin": "Antwerp", "destination": "Rotterdam", "cargo": "general"},
        "output_example": {"route_options": [], "risk_flags": [], "required_documents": []},
        "tags": ["logistics", "shipping", "supply-chain"],
    },
    {
        "slug": "local_business_data",
        "label": "Local business data",
        "concept_name": "LocalProof",
        "keywords": ["local", "business", "place", "restaurant", "store", "company", "opening hours", "address", "nearby"],
        "demand_prior": 0.83,
        "default_price_usd": 0.01,
        "build_difficulty": "easy",
        "target_buyer": "local discovery and sales prospecting agents",
        "promise": "Return a current, source-linked local-business fact pack instead of a generic directory row.",
        "path": "/v1/local-proof",
        "input_example": {"query": "industrial maintenance", "location": "Antwerp, BE"},
        "output_example": {"businesses": [], "source_checked_at": ""},
        "tags": ["local", "business-data", "prospecting"],
    },
    {
        "slug": "scientific_research",
        "label": "Scientific & technical research",
        "concept_name": "EvidenceMap",
        "keywords": ["research", "science", "paper", "study", "patent", "evidence", "technical", "clinical", "academic"],
        "demand_prior": 0.86,
        "default_price_usd": 0.05,
        "build_difficulty": "hard",
        "target_buyer": "research, engineering and patent agents",
        "promise": "Map a technical claim to supporting, conflicting and missing evidence.",
        "path": "/v1/evidence-map",
        "input_example": {"claim": "A precise technical claim", "date_cutoff": None},
        "output_example": {"supporting": [], "conflicting": [], "unknowns": []},
        "tags": ["research", "evidence", "technical"],
    },
    {
        "slug": "media_content_intelligence",
        "label": "Media & content intelligence",
        "concept_name": "ContentSignal",
        "keywords": ["video", "audio", "image", "media", "content", "youtube", "tiktok", "podcast", "transcript"],
        "demand_prior": 0.84,
        "default_price_usd": 0.015,
        "build_difficulty": "medium",
        "target_buyer": "content, monitoring and creative agents",
        "promise": "Convert media into structured claims, moments and reusable content signals.",
        "path": "/v1/content-signal",
        "input_example": {"url": "https://example.com/media", "tasks": ["key moments", "claims"]},
        "output_example": {"moments": [], "claims": [], "reuse_notes": []},
        "tags": ["media", "content", "analysis"],
    },
    {
        "slug": "ai_evaluation",
        "label": "AI evaluation & agent reliability",
        "concept_name": "AgentBenchNow",
        "keywords": ["agent", "model", "llm", "evaluation", "benchmark", "prompt", "hallucination", "quality", "ai"],
        "demand_prior": 0.97,
        "default_price_usd": 0.03,
        "build_difficulty": "medium",
        "target_buyer": "agent builders, model routers and AI product teams",
        "promise": "Run a small, decision-oriented reliability check on an agent response or tool flow.",
        "path": "/v1/agent-eval",
        "input_example": {"task": "", "response": "", "rubric": []},
        "output_example": {"score": 0, "failures": [], "recommended_fix": []},
        "tags": ["ai", "evaluation", "agents"],
    },
    {
        "slug": "data_enrichment",
        "label": "Data enrichment & verification",
        "concept_name": "RowProof",
        "keywords": ["enrich", "data", "lookup", "verify", "email", "domain", "company", "contact", "dataset"],
        "demand_prior": 0.87,
        "default_price_usd": 0.01,
        "build_difficulty": "easy",
        "target_buyer": "sales, CRM and data-cleaning agents",
        "promise": "Enrich one record and return field-level provenance and confidence.",
        "path": "/v1/row-proof",
        "input_example": {"record": {"company": "Example", "domain": "example.com"}},
        "output_example": {"record": {}, "provenance": {}, "confidence": {}},
        "tags": ["data", "enrichment", "verification"],
    },
    {
        "slug": "payments_finance_data",
        "label": "Payments & finance data",
        "concept_name": "PaymentContext",
        "keywords": ["payment", "finance", "exchange", "currency", "invoice", "bank", "market data", "stock", "crypto price"],
        "demand_prior": 0.89,
        "default_price_usd": 0.02,
        "build_difficulty": "medium",
        "target_buyer": "billing, treasury and commerce agents",
        "promise": "Explain a payment or price decision with current data while avoiding regulated execution.",
        "path": "/v1/payment-context",
        "input_example": {"question": "", "currency": "EUR"},
        "output_example": {"facts": [], "calculation": {}, "execution_performed": False},
        "tags": ["payments", "finance-data", "analysis"],
    },
    {
        "slug": "weather_geospatial",
        "label": "Weather & geospatial",
        "concept_name": "GeoDecision",
        "keywords": ["weather", "climate", "map", "geospatial", "location", "forecast", "satellite", "coordinates"],
        "demand_prior": 0.78,
        "default_price_usd": 0.005,
        "build_difficulty": "easy",
        "target_buyer": "travel, logistics, agriculture and field-service agents",
        "promise": "Return a decision, not just coordinates or a weather row.",
        "path": "/v1/geo-decision",
        "input_example": {"location": "Antwerp", "decision": "outdoor work suitability"},
        "output_example": {"recommendation": "", "factors": [], "valid_until": ""},
        "tags": ["weather", "geospatial", "decision"],
    },
    {
        "slug": "news_current_events",
        "label": "News & current events",
        "concept_name": "EventProof",
        "keywords": ["news", "current", "event", "headline", "article", "breaking", "press", "update"],
        "demand_prior": 0.88,
        "default_price_usd": 0.015,
        "build_difficulty": "medium",
        "target_buyer": "monitoring, research and decision-support agents",
        "promise": "Deduplicate an event and return what changed, when it happened and which sources agree.",
        "path": "/v1/event-proof",
        "input_example": {"topic": "", "since": "24h"},
        "output_example": {"events": [], "source_agreement": {}, "unknowns": []},
        "tags": ["news", "events", "verification"],
    },
    {
        "slug": "social_sentiment",
        "label": "Social & sentiment signals",
        "concept_name": "ConversationPulse",
        "keywords": ["social", "sentiment", "reddit", "twitter", "x.com", "community", "forum", "trend"],
        "demand_prior": 0.82,
        "default_price_usd": 0.015,
        "build_difficulty": "medium",
        "target_buyer": "brand, product and market-research agents",
        "promise": "Summarize a live conversation with sample bias and source coverage made explicit.",
        "path": "/v1/conversation-pulse",
        "input_example": {"topic": "", "sources": ["forums", "social"]},
        "output_example": {"themes": [], "sentiment": {}, "coverage_limits": []},
        "tags": ["social", "sentiment", "trends"],
    },
    {
        "slug": "translation_localization",
        "label": "Translation & localization",
        "concept_name": "IntentLocalize",
        "keywords": ["translate", "translation", "language", "localize", "localization", "multilingual"],
        "demand_prior": 0.76,
        "default_price_usd": 0.005,
        "build_difficulty": "easy",
        "target_buyer": "commerce, support and publishing agents",
        "promise": "Localize intent, tone and market-specific constraints rather than translating words only.",
        "path": "/v1/intent-localize",
        "input_example": {"text": "", "target_locale": "nl-BE", "context": "sales"},
        "output_example": {"localized_text": "", "adaptations": [], "uncertainties": []},
        "tags": ["translation", "localization", "content"],
    },
)

KNOWN_USDC_ASSETS = {
    "usdc",
    "usd coin",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # Base
    "0x036cbd53842c5426634e7929541ec2318f3dcf7e",  # Base Sepolia
    "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",  # Polygon
    "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e",  # Avalanche
    "epjfwdd5aufqssqem2qn1xzybapc8g4wegkzwytdt1v",  # Solana
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else None
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        try:
            result = float(match.group(0))
        except ValueError:
            return None
        return result if math.isfinite(result) else None
    return None


def _nested(mapping: dict[str, Any], *path: str) -> Any:
    value: Any = mapping
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _first(mapping: dict[str, Any], paths: Iterable[tuple[str, ...]]) -> Any:
    for path in paths:
        value = _nested(mapping, *path)
        if value not in (None, "", [], {}):
            return value
    return None


def extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("items", "resources", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = extract_items(value)
            if nested:
                return nested
    return []


def _accept_price_usd(accept: dict[str, Any]) -> tuple[float | None, str]:
    direct = _first(
        accept,
        (
            ("priceUsd",),
            ("price_usd",),
            ("usdPrice",),
            ("amountUsd",),
            ("amount_usd",),
            ("extra", "priceUsd"),
        ),
    )
    direct_value = _safe_float(direct)
    if direct_value is not None and direct_value >= 0:
        return direct_value, "declared_usd"

    price_field = accept.get("price")
    if isinstance(price_field, str) and ("$" in price_field or "usd" in price_field.lower() or "usdc" in price_field.lower()):
        parsed = _safe_float(price_field)
        if parsed is not None and parsed >= 0:
            return parsed, "declared_price_string"

    amount = _safe_float(accept.get("amount"))
    if amount is None or amount < 0:
        return None, "unavailable"

    asset = str(
        _first(
            accept,
            (("asset",), ("currency",), ("token",), ("extra", "asset"), ("extra", "symbol")),
        )
        or ""
    ).strip().lower()
    decimals = _safe_float(_first(accept, (("decimals",), ("extra", "decimals"))))

    if decimals is not None and 0 <= decimals <= 30:
        return amount / (10 ** int(decimals)), "asset_decimals"
    if asset in KNOWN_USDC_ASSETS or "usdc" in asset or "usd coin" in asset:
        return amount / 1_000_000, "usdc_6_decimals"
    return None, "unknown_asset_decimals"


def _resource_text(item: dict[str, Any], metadata: dict[str, Any]) -> str:
    values: list[str] = []
    for value in (
        item.get("name"),
        item.get("serviceName"),
        item.get("description"),
        item.get("resource"),
        item.get("url"),
        metadata.get("name"),
        metadata.get("serviceName"),
        metadata.get("description"),
        metadata.get("summary"),
    ):
        if isinstance(value, str):
            values.append(value)
    for source in (item.get("tags"), metadata.get("tags")):
        if isinstance(source, list):
            values.extend(str(value) for value in source)
        elif isinstance(source, str):
            values.append(source)
    return " ".join(values).lower()


def _host_label(url: str) -> str:
    try:
        host = urlparse(url).hostname or "unnamed service"
    except ValueError:
        host = "unnamed service"
    return host.removeprefix("www.")


def normalize_resource(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    resource_url = str(
        _first(item, (("resource",), ("url",), ("endpoint",), ("resourceUrl",), ("uri",)))
        or ""
    ).strip()
    accepts = item.get("accepts") if isinstance(item.get("accepts"), list) else []
    accepts = [entry for entry in accepts if isinstance(entry, dict)]

    prices: list[float] = []
    price_methods: list[str] = []
    networks: list[str] = []
    assets: list[str] = []
    for accept in accepts:
        price, method = _accept_price_usd(accept)
        if price is not None:
            prices.append(price)
            price_methods.append(method)
        network = accept.get("network")
        if network:
            networks.append(str(network))
        asset = accept.get("asset") or accept.get("currency") or accept.get("token")
        if asset:
            assets.append(str(asset))

    quality = item.get("quality") if isinstance(item.get("quality"), dict) else {}
    calls = _safe_float(
        _first(
            quality,
            (
                ("l30DaysTotalCalls",),
                ("last30DaysTotalCalls",),
                ("calls30d",),
                ("totalCalls",),
            ),
        )
    )
    tags_value = metadata.get("tags", item.get("tags", []))
    if isinstance(tags_value, str):
        tags = [part.strip() for part in re.split(r"[,;]", tags_value) if part.strip()]
    elif isinstance(tags_value, list):
        tags = [str(value) for value in tags_value]
    else:
        tags = []

    method = str(
        _first(item, (("method",), ("httpMethod",), ("verb",), ("metadata", "method")))
        or ""
    ).upper()
    item_type = str(item.get("type") or "http").lower()
    if not method:
        method = "MCP" if item_type == "mcp" else "UNKNOWN"

    service_name = str(
        _first(
            item,
            (
                ("serviceName",),
                ("name",),
                ("metadata", "serviceName"),
                ("metadata", "name"),
            ),
        )
        or _host_label(resource_url)
    )
    description = str(
        _first(item, (("description",), ("metadata", "description"), ("metadata", "summary")))
        or ""
    )
    source = str(item.get("_source") or "unknown")
    fingerprint_input = f"{resource_url}|{method}|{item_type}".encode("utf-8", errors="ignore")
    fingerprint = hashlib.sha256(fingerprint_input).hexdigest()[:20]

    return {
        "resource_id": fingerprint,
        "resource": resource_url,
        "service_name": service_name,
        "description": description,
        "type": item_type,
        "method": method,
        "tags": tags,
        "accepts": accepts,
        "networks": sorted(set(networks)),
        "assets": sorted(set(assets)),
        "min_price_usd": min(prices) if prices else None,
        "price_observations_usd": prices,
        "price_parse_methods": sorted(set(price_methods)),
        "calls_30d": int(calls) if calls is not None and calls >= 0 else None,
        "last_updated": _first(item, (("lastUpdated",), ("last_updated",), ("updatedAt",), ("updated_at",))),
        "source": source,
        "text": _resource_text(item, metadata),
    }


def normalize_and_dedupe(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for raw in raw_items:
        normalized = normalize_resource(raw)
        key = normalized["resource_id"]
        if key not in merged:
            normalized["sources"] = [normalized.pop("source")]
            merged[key] = normalized
            continue
        existing = merged[key]
        source = normalized.pop("source")
        existing["sources"] = sorted(set(existing["sources"] + [source]))
        existing["networks"] = sorted(set(existing["networks"] + normalized["networks"]))
        existing["assets"] = sorted(set(existing["assets"] + normalized["assets"]))
        existing["tags"] = sorted(set(existing["tags"] + normalized["tags"]))
        existing["accepts"] = existing["accepts"] + normalized["accepts"]
        prices = existing["price_observations_usd"] + normalized["price_observations_usd"]
        existing["price_observations_usd"] = prices
        existing["min_price_usd"] = min(prices) if prices else None
        existing["price_parse_methods"] = sorted(
            set(existing["price_parse_methods"] + normalized["price_parse_methods"])
        )
        if not existing["description"] and normalized["description"]:
            existing["description"] = normalized["description"]
        if normalized["calls_30d"] is not None:
            existing["calls_30d"] = max(existing["calls_30d"] or 0, normalized["calls_30d"])
    return list(merged.values())


def _keyword_hits(text: str, category: dict[str, Any]) -> int:
    return sum(1 for keyword in category["keywords"] if keyword in text)


def match_category(resource: dict[str, Any]) -> str:
    text = resource["text"]
    ranked = [(_keyword_hits(text, category), category["slug"]) for category in TAXONOMY]
    hits, slug = max(ranked, key=lambda pair: pair[0])
    return slug if hits > 0 else "other"


def _round_price(value: float) -> float:
    if value < 0.01:
        return round(value, 4)
    if value < 0.1:
        return round(value, 3)
    return round(value, 2)


def _suggested_price(default_price: float, observed_median: float | None) -> float:
    if observed_median is None or observed_median <= 0:
        return _round_price(default_price)
    candidate = observed_median * 0.8
    lower = max(0.001, default_price * 0.35)
    upper = max(default_price * 2.5, lower)
    return _round_price(min(max(candidate, lower), upper))


def _confidence(total: int, observed: int, data_mode: str) -> str:
    if data_mode != "live":
        return "low"
    if total >= 100 and observed >= 3:
        return "high"
    if total >= 25:
        return "medium"
    return "low"


def build_intelligence(
    raw_items: list[dict[str, Any]],
    *,
    source_status: list[dict[str, Any]] | None = None,
    data_mode: str = "live",
    captured_at: str | None = None,
) -> dict[str, Any]:
    captured_at = captured_at or utc_now_iso()
    resources = normalize_and_dedupe(raw_items)
    total = len(resources)

    buckets: dict[str, list[dict[str, Any]]] = {category["slug"]: [] for category in TAXONOMY}
    other: list[dict[str, Any]] = []
    for resource in resources:
        category = match_category(resource)
        resource["primary_category"] = category
        if category == "other":
            other.append(resource)
        else:
            buckets[category].append(resource)

    all_prices = [
        resource["min_price_usd"]
        for resource in resources
        if isinstance(resource.get("min_price_usd"), (int, float))
    ]
    network_counts = Counter(network for resource in resources for network in resource["networks"])
    type_counts = Counter(resource["type"] for resource in resources)

    opportunities: list[dict[str, Any]] = []
    coverage_target = max(2.0, total * 0.08)
    for category in TAXONOMY:
        observed_resources = buckets[category["slug"]]
        observed = len(observed_resources)
        category_prices = [
            resource["min_price_usd"]
            for resource in observed_resources
            if isinstance(resource.get("min_price_usd"), (int, float))
        ]
        median_price = statistics.median(category_prices) if category_prices else None
        scarcity = 1.0 - min(observed / coverage_target, 1.0)
        monetization = (
            min(1.0, max(0.1, math.log10(1 + median_price * 1000) / 3.0))
            if median_price is not None
            else 0.45
        )
        calls = sum(resource.get("calls_30d") or 0 for resource in observed_resources)
        activity = min(1.0, math.log10(calls + 1) / 5.0) if calls else 0.35
        score = round(
            100
            * (
                0.55 * scarcity
                + 0.30 * float(category["demand_prior"])
                + 0.10 * monetization
                + 0.05 * activity
            ),
            1,
        )
        examples = sorted(
            observed_resources,
            key=lambda resource: (resource.get("calls_30d") or 0, bool(resource.get("description"))),
            reverse=True,
        )[:4]
        suggested = _suggested_price(float(category["default_price_usd"]), median_price)
        opportunities.append(
            {
                "category": category["slug"],
                "category_label": category["label"],
                "opportunity_score": score,
                "confidence": _confidence(total, observed, data_mode),
                "concept_name": category["concept_name"],
                "one_line_product": category["promise"],
                "target_buyer": category["target_buyer"],
                "suggested_x402_price_usd": suggested,
                "first_paid_endpoint": category["path"],
                "build_difficulty": category["build_difficulty"],
                "evidence": {
                    "resources_observed": observed,
                    "catalog_share_pct": round((observed / total * 100), 2) if total else 0.0,
                    "observed_median_price_usd": _round_price(median_price) if median_price is not None else None,
                    "observed_30d_calls": calls if calls else None,
                    "sample_services": [
                        {
                            "name": resource["service_name"],
                            "resource": resource["resource"],
                            "price_usd": resource["min_price_usd"],
                            "sources": resource["sources"],
                        }
                        for resource in examples
                    ],
                },
                "why_now": (
                    f"Only {observed} of {total} observed resources primarily map to this category; "
                    "the score rewards scarcity, a disclosed demand prior, price evidence and visible activity."
                ),
            }
        )

    opportunities.sort(key=lambda opportunity: opportunity["opportunity_score"], reverse=True)
    for rank, opportunity in enumerate(opportunities, start=1):
        opportunity["rank"] = rank

    top_resources = sorted(
        resources,
        key=lambda resource: (resource.get("calls_30d") or 0, bool(resource.get("description"))),
        reverse=True,
    )[:10]

    return {
        "protocol": "capi2.x402-opportunity-radar/1.0",
        "captured_at": captured_at,
        "data_mode": data_mode,
        "source_status": source_status or [],
        "methodology": {
            "score_formula": "55% catalog scarcity + 30% disclosed demand prior + 10% price signal + 5% visible activity",
            "important": "The score is a prioritization heuristic, not a revenue forecast or proof of customer demand.",
            "catalog_caveat": "Discovery catalogs can contain stale or incomplete seller metadata; verify endpoint liveness before investing.",
            "price_method": "Declared USD prices are used directly. Recognized USDC atomic amounts are converted using six decimals; unknown assets are excluded from price benchmarks.",
        },
        "metrics": {
            "resources_observed": total,
            "resources_with_parseable_price": len(all_prices),
            "median_price_usd": _round_price(statistics.median(all_prices)) if all_prices else None,
            "minimum_price_usd": _round_price(min(all_prices)) if all_prices else None,
            "maximum_price_usd": _round_price(max(all_prices)) if all_prices else None,
            "network_distribution": dict(network_counts.most_common()),
            "type_distribution": dict(type_counts.most_common()),
            "uncategorized_resources": len(other),
        },
        "opportunities": opportunities,
        "top_visible_resources": [
            {
                "name": resource["service_name"],
                "resource": resource["resource"],
                "category": resource["primary_category"],
                "price_usd": resource["min_price_usd"],
                "calls_30d": resource["calls_30d"],
                "sources": resource["sources"],
            }
            for resource in top_resources
        ],
        "resources": resources,
    }


def _taxonomy_by_slug(slug: str) -> dict[str, Any] | None:
    return next((category for category in TAXONOMY if category["slug"] == slug), None)


def build_launch_brief(
    intelligence: dict[str, Any],
    *,
    category_slug: str,
    target_buyer: str | None = None,
    max_build_days: int = 7,
) -> dict[str, Any]:
    category = _taxonomy_by_slug(category_slug)
    if category is None:
        raise KeyError(category_slug)
    opportunity = next(
        opportunity
        for opportunity in intelligence["opportunities"]
        if opportunity["category"] == category_slug
    )
    buyer = target_buyer.strip() if target_buyer and target_buyer.strip() else category["target_buyer"]
    price = float(opportunity["suggested_x402_price_usd"])
    endpoint = category["path"]

    return {
        "protocol": "capi2.launch-brief/1.0",
        "generated_at": utc_now_iso(),
        "source_snapshot": {
            "captured_at": intelligence["captured_at"],
            "data_mode": intelligence["data_mode"],
            "resources_observed": intelligence["metrics"]["resources_observed"],
        },
        "decision": {
            "build": category["concept_name"],
            "positioning": category["promise"],
            "target_buyer": buyer,
            "opportunity_rank": opportunity["rank"],
            "opportunity_score": opportunity["opportunity_score"],
            "confidence": opportunity["confidence"],
            "build_window_days": max_build_days,
        },
        "evidence": opportunity["evidence"],
        "commercial_offer": {
            "billing_model": "x402 per successful request",
            "launch_price_usd": price,
            "price_rationale": "Starts near the category benchmark while discounting for a new provider without reputation.",
            "human_pilot_offer": "€49 setup plus 100 included calls for the first three design partners",
        },
        "minimum_sellable_api": {
            "endpoints": [
                {"method": "GET", "path": "/health", "price_usd": 0, "purpose": "liveness"},
                {"method": "GET", "path": "/.well-known/agent.json", "price_usd": 0, "purpose": "agent discovery"},
                {"method": "GET", "path": "/v1/quote", "price_usd": 0, "purpose": "machine-readable price quote"},
                {"method": "POST", "path": endpoint, "price_usd": price, "purpose": category["promise"]},
            ],
            "request_example": category["input_example"],
            "response_contract": category["output_example"],
            "non_negotiable_fields": ["request_id", "generated_at", "sources", "confidence", "limitations"],
        },
        "x402_discovery_declaration": {
            "resource": f"https://your-domain.example{endpoint}",
            "type": "http",
            "method": "POST",
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:8453",
                    "asset": "USDC",
                    "price": f"${price:g}",
                }
            ],
            "metadata": {
                "serviceName": category["concept_name"],
                "description": category["promise"],
                "tags": category["tags"],
                "input": {"type": "object", "example": category["input_example"]},
                "output": {"type": "object", "example": category["output_example"]},
            },
        },
        "seven_day_launch": [
            {"day": 1, "deliverable": "Lock the single buyer, input contract and paid outcome; reject feature creep."},
            {"day": 2, "deliverable": "Implement the free manifest, quote endpoint and deterministic response schema."},
            {"day": 3, "deliverable": "Implement the core data/evidence pipeline with timeouts, provenance and no invented facts."},
            {"day": 4, "deliverable": "Add x402 payment enforcement, idempotency and complete settlement/error logging."},
            {"day": 5, "deliverable": "Create ten golden tests, three failure tests and a public curl example."},
            {"day": 6, "deliverable": "Publish to at least two Bazaar/facilitator discovery surfaces and the capi2 router."},
            {"day": 7, "deliverable": "Send a concrete paid pilot request to 20 reachable builders using the exact endpoint output."},
        ][: max(1, min(max_build_days, 7))],
        "first_sales_message": (
            f"We built {category['concept_name']} for {buyer}. Send one real input and it returns "
            f"{category['promise'].lower()} The public quote is ${price:g} per successful call; "
            "I will run one evidence-backed sample before asking you to integrate."
        ),
        "validation_gates": [
            "At least three target buyers independently confirm the output replaces a current manual step.",
            "At least one external buyer completes a non-test paid call.",
            "Median delivery cost remains below 40% of selling price.",
            "Every factual output includes provenance or an explicit unknown state.",
        ],
        "risks": [
            "Catalog scarcity is not the same as willingness to pay.",
            "Discovery records may be stale; probe the unpaid endpoint and expect a valid 402 before using competitor counts.",
            "A new seller has no reputation; start with narrow outputs and signed receipts where supported.",
            "Do not perform regulated execution or present analysis as legal, financial or medical advice.",
        ],
    }


def public_snapshot(intelligence: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol": intelligence["protocol"],
        "captured_at": intelligence["captured_at"],
        "data_mode": intelligence["data_mode"],
        "source_status": intelligence["source_status"],
        "methodology": intelligence["methodology"],
        "metrics": intelligence["metrics"],
        "opportunity_preview": [
            {
                "rank": opportunity["rank"],
                "category": opportunity["category"],
                "category_label": opportunity["category_label"],
                "opportunity_score": opportunity["opportunity_score"],
                "confidence": opportunity["confidence"],
                "resources_observed": opportunity["evidence"]["resources_observed"],
                "suggested_x402_price_usd": opportunity["suggested_x402_price_usd"],
            }
            for opportunity in intelligence["opportunities"][:3]
        ],
        "upgrade": {
            "includes": [
                "full ranked opportunity list",
                "category evidence and price benchmarks",
                "machine-readable launch brief generator",
                "API access for agents and automations",
            ]
        },
    }


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
