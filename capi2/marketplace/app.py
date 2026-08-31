"""Marketplace application with AckMint and commercial offers installed."""

from __future__ import annotations

import time
from typing import Any

from x402.extensions import bazaar as x402_bazaar

from . import legacy_app as marketplace
from .legacy_app import app
from capi2.ackmint import core
from capi2.ackmint.integration import install
from capi2.revenue_offers.integration import install as install_revenue_offers


# x402 2.21 creates the POST body schema correctly but its startup validator
# runs before route enrichment adds the HTTP method. Add the route method to the
# declaration up front, then immediately restore the SDK function after install.
_original_declare = x402_bazaar.declare_discovery_extension


def _declare_post_discovery_extension(*args: Any, **kwargs: Any) -> dict[str, Any]:
    extension = _original_declare(*args, **kwargs)
    try:
        input_info = extension["bazaar"]["info"]["input"]
        if input_info.get("type") == "http" and "bodyType" in input_info:
            input_info["method"] = "POST"
    except (KeyError, TypeError, AttributeError):
        pass
    return extension


x402_bazaar.declare_discovery_extension = _declare_post_discovery_extension
try:
    install(app, marketplace)
finally:
    x402_bazaar.declare_discovery_extension = _original_declare

install_revenue_offers(app, marketplace)


@app.on_event("startup")
def verify_ackmint_persistent_ledger() -> None:
    """Fail closed when the paid product cannot persist delivery receipts."""

    last_error: Exception | None = None
    for delay in (0.0, 0.5, 1.5):
        if delay:
            time.sleep(delay)
        try:
            core.init_db()
            stats = core.stats_sync()
            print(
                "AckMint ready: persistent ledger connected; "
                f"retained_deliveries={stats['retained_successful_deliveries']}; "
                f"integrations={stats['integrations_with_successful_delivery']}"
            )
            return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(
        "AckMint persistent ledger is unavailable: "
        f"{last_error.__class__.__name__ if last_error else 'unknown'}"
    ) from last_error
