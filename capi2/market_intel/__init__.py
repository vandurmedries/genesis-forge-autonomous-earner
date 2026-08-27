"""CAPI2 NextEndpoint — x402 supply-gap intelligence and launch contracts."""

from __future__ import annotations

import json

from . import app as _module

# Keep capi2 as the internal name while avoiding confusion with an existing
# provider-ranking product called 402radar. NextEndpoint answers a different
# question: what paid endpoint should be built next, and how should it launch?
_module.PRODUCT_NAME = "CAPI2 NextEndpoint"
_module.app.title = _module.PRODUCT_NAME
_module.app.description = (
    "Find the next x402 endpoint worth validating, then generate its price, "
    "machine contract and seven-day launch brief."
)
_module.LANDING_PAGE = (
    _module.LANDING_PAGE
    .replace("CAPI2 x402 Opportunity Radar", "CAPI2 NextEndpoint")
    .replace("CAPI2 / RADAR", "CAPI2 / NEXTENDPOINT")
    .replace("CAPI2 x402 Opportunity Radar</span>", "CAPI2 NextEndpoint</span>")
    .replace("Build what the x402 market is missing.", "Build the next endpoint agents will pay for.")
)


@_module.app.on_event("startup")
async def _warm_live_market_snapshot() -> None:
    """Warm the first snapshot and leave a compact, auditable deploy trace."""
    try:
        intelligence = await _module._load_intelligence(force=True)
        print(
            "NEXTENDPOINT_WARMUP "
            + json.dumps(
                {
                    "data_mode": intelligence["data_mode"],
                    "resources_observed": intelligence["metrics"]["resources_observed"],
                    "parseable_prices": intelligence["metrics"]["resources_with_parseable_price"],
                    "sources": intelligence["source_status"],
                    "captured_at": intelligence["captured_at"],
                },
                separators=(",", ":"),
            )
        )
    except Exception as exc:  # Startup must remain available even if an upstream catalog fails.
        print(f"NEXTENDPOINT_WARMUP_FAILED {exc.__class__.__name__}: {str(exc)[:240]}")


app = _module.app

__all__ = ["app"]
