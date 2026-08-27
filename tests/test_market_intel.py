from capi2.market_intel.core import build_intelligence, build_launch_brief, public_snapshot


def _item(resource: str, description: str, amount: str, tags: list[str]):
    return {
        "_source": "test",
        "resource": resource,
        "type": "http",
        "method": "POST",
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "asset": "USDC",
                "amount": amount,
            }
        ],
        "metadata": {
            "serviceName": resource.rsplit("/", 1)[-1],
            "description": description,
            "tags": tags,
        },
    }


def test_build_intelligence_converts_usdc_atomic_amounts():
    intelligence = build_intelligence(
        [
            _item("https://example.test/pdf", "Extract a PDF document", "10000", ["pdf", "document"]),
            _item("https://example.test/weather", "Weather forecast", "5000", ["weather"]),
        ],
        source_status=[{"name": "test", "ok": True, "items": 2}],
        data_mode="live",
    )

    assert intelligence["metrics"]["resources_observed"] == 2
    assert intelligence["metrics"]["resources_with_parseable_price"] == 2
    assert intelligence["metrics"]["minimum_price_usd"] == 0.005
    assert intelligence["metrics"]["maximum_price_usd"] == 0.01
    assert any(item["category"] == "document_extraction" for item in intelligence["opportunities"])


def test_public_snapshot_does_not_expose_full_catalog():
    intelligence = build_intelligence(
        [_item("https://example.test/code", "GitHub code audit", "20000", ["code", "audit"])],
        data_mode="live",
    )
    snapshot = public_snapshot(intelligence)

    assert "resources" not in snapshot
    assert "opportunities" not in snapshot
    assert len(snapshot["opportunity_preview"]) == 3


def test_launch_brief_is_machine_ready():
    intelligence = build_intelligence(
        [_item("https://example.test/eval", "AI agent evaluation", "30000", ["agent", "evaluation"])],
        data_mode="live",
    )
    brief = build_launch_brief(
        intelligence,
        category_slug="ai_evaluation",
        target_buyer="small agent platforms",
        max_build_days=7,
    )

    assert brief["decision"]["target_buyer"] == "small agent platforms"
    assert brief["minimum_sellable_api"]["endpoints"][-1]["method"] == "POST"
    assert brief["x402_discovery_declaration"]["accepts"][0]["asset"] == "USDC"
    assert len(brief["seven_day_launch"]) == 7
