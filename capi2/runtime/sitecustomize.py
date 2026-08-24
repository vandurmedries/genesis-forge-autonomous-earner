"""Claim Verify runtime bootstrap.

Render can disable Python's automatic usercustomize import.  This sitecustomize
wrapper is placed first on PYTHONPATH for the Claim Verify service.  It loads
the repository-wide sitecustomize under an alias, then explicitly imports the
narrow Claim Verify verdict guard from usercustomize.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ROOT_SITE = _ROOT / "sitecustomize.py"

if _ROOT_SITE.is_file():
    spec = importlib.util.spec_from_file_location("_capi2_root_sitecustomize", _ROOT_SITE)
    if spec is not None and spec.loader is not None:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

try:
    import usercustomize  # noqa: F401
    print("claim-runtime-bootstrap: usercustomize imported", flush=True)
except Exception as exc:
    print(f"claim-runtime-bootstrap: usercustomize error {type(exc).__name__}: {exc}", flush=True)
