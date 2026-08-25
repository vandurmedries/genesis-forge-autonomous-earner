"""capi2 x402 service package.

Render currently starts ``uvicorn capi2.x402_service.app:app``. Import the sales
surface at package initialization so that the live app receives the intent-specific
paid routes and x402scan/OpenAPI discovery metadata even with that legacy start
command. Python module caching prevents duplicate registration.
"""

from . import sales_app as _sales_app  # noqa: F401
