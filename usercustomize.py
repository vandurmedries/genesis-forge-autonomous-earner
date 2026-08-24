"""Temporary-safe runtime diagnostics for external x402 directory registration.

Python imports usercustomize after sitecustomize when the repo root is on
PYTHONPATH. This wrapper does not alter requests or registration semantics; it
only surfaces the compact Agent402 response body so a `listed=false` result is
diagnosable from Render logs. Other HTTP traffic is unchanged.
"""

from __future__ import annotations

try:
    import requests
except Exception:
    requests = None

if requests is not None:
    _original_post = requests.post

    def _capi2_post(url, *args, **kwargs):
        response = _original_post(url, *args, **kwargs)
        if str(url).rstrip("/") == "https://agent402.tools/api/index/register":
            try:
                body = response.text.replace("\n", " ")[:3000]
                print(
                    f"agent402-register-response: status={response.status_code} body={body}",
                    flush=True,
                )
            except Exception as exc:
                print(
                    f"agent402-register-response: status={getattr(response, 'status_code', None)} read_error={type(exc).__name__}",
                    flush=True,
                )
        return response

    if not getattr(requests.post, "_capi2_agent402_diagnostics", False):
        _capi2_post._capi2_agent402_diagnostics = True
        requests.post = _capi2_post
