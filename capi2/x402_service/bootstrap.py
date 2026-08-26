"""Render production entrypoint for capi2 Claim Verify."""
from __future__ import annotations

import os

# Production and fallback use the same facilitator. Render also sets this
# explicitly; setdefault prevents local/test environments from drifting back
# to the obsolete PayAI default.
os.environ.setdefault("CAPI2_X402_FACILITATOR", "https://facilitator.xpay.sh")

# Must run before importing app/sales_app so the native x402 2.20.0 settlement
# method is restored before PaymentMiddlewareASGI handles any request.
import x402_runtime_fix  # noqa: F401,E402
import app as _app_module  # noqa: E402
from claim_classifier_fix import install as _install_claim_classifier  # noqa: E402

_install_claim_classifier(_app_module)
from sales_app import app  # noqa: E402,F401
