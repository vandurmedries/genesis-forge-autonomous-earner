"""Narrow Python startup compatibility guard for capi2 x402 production.

The repository sitecustomize may install a settlement observability wrapper.
This hook restores the native x402 SDK settlement method before application
imports when that wrapper is present. It intentionally validates only the
stable required parameters so newer x402 releases can add optional settlement
arguments without being rejected.

During Render build-tool startup x402 may not be installed yet; that case is
expected and ignored.
"""
from __future__ import annotations

import inspect

try:
    from x402.http.x402_http_server import x402HTTPResourceServer
except ModuleNotFoundError as exc:
    if exc.name and (exc.name == "x402" or exc.name.startswith("x402.")):
        print("x402-runtime-fix: deferred until x402 dependency is installed", flush=True)
    else:
        raise
else:
    current = x402HTTPResourceServer.process_settlement
    if getattr(current, "_capi2_settlement_logger", False):
        nonlocals = inspect.getclosurevars(current).nonlocals
        native = nonlocals.get("original")
        if not callable(native):
            raise RuntimeError("cannot recover native x402 process_settlement from capi2 wrapper")
        x402HTTPResourceServer.process_settlement = native
        current = native

    signature = inspect.signature(current)
    params = set(signature.parameters)
    required = {"self", "payment_payload", "requirements"}
    if not required.issubset(params):
        raise RuntimeError(f"unexpected x402 process_settlement signature: {signature}")

    print(f"x402-runtime-fix: native process_settlement active signature={signature}", flush=True)
