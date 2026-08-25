"""Render production entrypoint for capi2 Claim Verify."""
from __future__ import annotations

import os

# Production and fallback use the same facilitator. Render also sets this
# explicitly; setdefault prevents local/test environments from drifting back
# to the obsolete PayAI default.
os.environ.setdefault("CAPI2_X402_FACILITATOR", "https://facilitator.xpay.sh")

# Must run before importing sales_app/app so the native x402 2.20.0 settlement
# method is restored before PaymentMiddlewareASGI handles any request.
import x402_runtime_fix  # noqa: F401,E402
from sales_app import app  # noqa: E402,F401
