"""Repository usercustomize intentionally left side-effect free.

Claim Verify verdict logic and its free dry-run/regression surface now live in
capi2/x402_service/app.py directly.  Keeping a second FastAPI/Pydantic monkey
patch here caused OpenAPI generation to fail under Pydantic 2.13 because a
locally-scoped request model survived as an unresolved ForwardRef.

Do not add payment, verdict, or FastAPI runtime patches here. Production x402
compatibility is handled explicitly by capi2/x402_service/bootstrap.py and
x402_runtime_fix.py.
"""
