"""Claim Verify runtime bootstrap.

This module is placed first on PYTHONPATH for the Claim Verify Render service.
It loads the repository-wide sitecustomize under an alias and then loads the
Claim Verify verdict guard from an explicit file path, avoiding Python user-site
or module-name ambiguity.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _load(alias: str, path: Path):
    if not path.is_file():
        raise FileNotFoundError(str(path))
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    _load("_capi2_root_sitecustomize", _ROOT / "sitecustomize.py")
except Exception as exc:
    print(f"claim-runtime-bootstrap: root sitecustomize error {type(exc).__name__}: {exc}", flush=True)

try:
    guard = _load("_capi2_claim_usercustomize", _ROOT / "usercustomize.py")
    from fastapi import FastAPI

    print(
        "claim-runtime-bootstrap: guard_file="
        f"{getattr(guard, '__file__', None)} "
        f"init_patched={getattr(FastAPI.__init__, '_capi2_claim_sandbox', False)} "
        f"route_patched={getattr(FastAPI.add_api_route, '_capi2_claim_guard', False)}",
        flush=True,
    )
except Exception as exc:
    print(f"claim-runtime-bootstrap: claim guard error {type(exc).__name__}: {exc}", flush=True)
