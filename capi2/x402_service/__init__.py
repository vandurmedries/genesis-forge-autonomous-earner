"""capi2 x402 service package.

Render currently starts ``uvicorn capi2.x402_service.app:app``. Import the sales
surface at package initialization so that the live app receives the intent-specific
paid routes. Then install a deterministic OpenAPI discovery contract so x402scan
does not depend on introspecting unrelated runtime-added sandbox routes.
"""

from . import sales_app as _sales_app  # noqa: F401
from . import discovery_contract as _discovery_contract  # noqa: F401
