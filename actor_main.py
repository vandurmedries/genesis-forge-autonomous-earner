"""Apify entry point for the capi2 Agent Intelligence Toolkit."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable

os.environ.setdefault("CAPI2_AGENT402_REGISTER", "false")
os.environ.setdefault("CAPI2_TRUE402_REGISTER", "false")

from apify import Actor

from capi2.demand_tools.app import (
    DomainIntelligenceRequest,
    EvidenceExtractRequest,
    UrlAuditRequest,
    WebLookupRequest,
    api_audit,
    domain_intelligence,
    evidence_extract,
    web_lookup,
)
from capi2.x402_service.app import ClaimVerifyRequest, claim_verify


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError("tool_result_is_not_json_object")


def execute_tool(actor_input: dict[str, Any]) -> dict[str, Any]:
    tool = actor_input.get("tool")
    handlers: dict[str, tuple[type, Callable[[Any], Any], dict[str, Any]]] = {
        "claim_verify": (
            ClaimVerifyRequest,
            claim_verify,
            {
                "vendor_url": actor_input.get("url"),
                "claim": actor_input.get("query"),
                "request_type": actor_input.get("request_type", "fact_check"),
            },
        ),
        "evidence_extract": (
            EvidenceExtractRequest,
            evidence_extract,
            {
                "url": actor_input.get("url"),
                "query": actor_input.get("query"),
                "max_passages": actor_input.get("max_passages", 5),
            },
        ),
        "domain_intelligence": (
            DomainIntelligenceRequest,
            domain_intelligence,
            {
                "domain": actor_input.get("domain"),
                "include_rdap": actor_input.get("include_rdap", True),
            },
        ),
        "web_lookup": (
            WebLookupRequest,
            web_lookup,
            {
                "url": actor_input.get("url"),
                "query": actor_input.get("query"),
                "max_bytes": actor_input.get("max_bytes", 200000),
            },
        ),
        "api_audit": (
            UrlAuditRequest,
            api_audit,
            {"url": actor_input.get("url")},
        ),
    }
    if tool not in handlers:
        raise ValueError("unsupported_tool")
    model, handler, data = handlers[tool]
    payload = model(**data)
    result = _as_dict(handler(payload))
    return {
        "tool": tool,
        "status": "completed",
        "result": result,
        "source": "capi2",
        "billable_event": "result",
    }


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        result = await asyncio.to_thread(execute_tool, actor_input)
        charge = await Actor.push_data(result, charged_event_name="result")
        Actor.log.info(
            "Stored result; charged_count=%s limit_reached=%s",
            getattr(charge, "charged_count", None),
            getattr(charge, "event_charge_limit_reached", None),
        )


if __name__ == "__main__":
    asyncio.run(main())
