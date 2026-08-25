"""Repository startup hook for narrow production compatibility only.

Claim Verify verdict and sandbox logic live directly in capi2/x402_service/app.py.
This hook performs one safe startup action: after repository sitecustomize has
loaded, restore the native x402 2.20.0 HTTP settlement method before the
FastAPI application module is imported.

During Render build commands x402 may not be installed yet, so dependency
absence is deliberately ignored. At runtime the pinned dependency is present
and the guard must install successfully.
"""
from __future__ import annotations

try:
    import capi2.x402_service.x402_runtime_fix  # noqa: F401
except ModuleNotFoundError as exc:
    # Expected during early build-tool Python startup before requirements are
    # installed. Do not break pip/build initialization.
    print(f"x402-runtime-fix: deferred until runtime ({exc})", flush=True)
