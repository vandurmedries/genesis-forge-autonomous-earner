"""capi2 x402 service package.

Render currently starts ``uvicorn capi2.x402_service.app:app``. Import the sales
surface at package initialization so that the live app receives the intent-specific
paid routes. Then install deterministic claim-classifier hardening, discovery,
and non-invasive settlement observability.
"""
from __future__ import annotations

from . import sales_app as _sales_app  # noqa: F401
from . import discovery_contract as _discovery_contract  # noqa: F401
from . import app as _app_module
from .claim_classifier_fix import (
    CLASSIFIER_REVISION as _CLASSIFIER_REVISION,
    install as _install_claim_classifier,
)
from .settlement_observability import install as _install_settlement_observability

_XPAY_FACILITATOR = "https://facilitator.xpay.sh"
_effective_facilitator = _app_module.FACILITATOR_URL.rstrip("/")

# Fail closed in production rather than silently drifting back to the obsolete
# PayAI fallback. Render also pins this value as an environment variable.
if _effective_facilitator != _XPAY_FACILITATOR:
    raise RuntimeError(
        "refusing startup: capi2 Claim Verify facilitator is not xpay: "
        f"{_effective_facilitator}"
    )

_install_claim_classifier(_app_module)
_install_settlement_observability(_sales_app.server, _effective_facilitator)
print(
    "capi2-runtime: "
    f"version={_app_module.SERVICE_VERSION} "
    f"network={_app_module.NETWORK} "
    f"facilitator={_effective_facilitator} "
    f"classifier={_CLASSIFIER_REVISION}",
    flush=True,
)
