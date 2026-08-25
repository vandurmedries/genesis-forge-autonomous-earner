"""Production compatibility guard for x402 2.20.0.

The repository-level sitecustomize historically wrapped
x402HTTPResourceServer.process_settlement for observability.  That wrapper
passed keyword arguments introduced by a different SDK shape and could turn a
valid paid request into HTTP 402 after verification.

This module is intentionally conservative: if that known wrapper is present,
it restores the native SDK method captured in the wrapper closure.  It does
not replace settlement logic, filter arguments, or alter payment semantics.
"""
from __future__ import annotations

import inspect


def restore_native_process_settlement() -> None:
    from x402.http.x402_http_server import x402HTTPResourceServer

    current = x402HTTPResourceServer.process_settlement

    if getattr(current, "_capi2_settlement_logger", False):
        try:
            nonlocals = inspect.getclosurevars(current).nonlocals
            native = nonlocals.get("original")
        except Exception as exc:  # fail closed rather than silently changing payments
            raise RuntimeError(
                f"cannot inspect capi2 settlement wrapper: {type(exc).__name__}: {exc}"
            ) from exc

        if not callable(native):
            raise RuntimeError("capi2 settlement wrapper did not expose its native original")

        x402HTTPResourceServer.process_settlement = native
        current = native

    signature = inspect.signature(current)
    params = set(signature.parameters)
    required = {"self", "payment_payload", "requirements"}
    unexpected_legacy = {"before_handler_settlement", "phase"} & params

    if not required.issubset(params):
        raise RuntimeError(f"unexpected x402 process_settlement signature: {signature}")
    if unexpected_legacy:
        raise RuntimeError(
            "refusing startup: incompatible settlement parameters still present: "
            + ", ".join(sorted(unexpected_legacy))
        )

    print(f"x402-runtime-fix: native process_settlement active signature={signature}", flush=True)


restore_native_process_settlement()
