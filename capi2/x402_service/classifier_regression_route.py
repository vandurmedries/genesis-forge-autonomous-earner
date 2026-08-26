"""Read-only regression status endpoint for the Claim Verify classifier."""
from __future__ import annotations

from typing import Any

REGRESSION_PATH = "/v1/claim-verify/classifier-regressions"


def install(app_module: Any) -> None:
    if any(getattr(route, "path", None) == REGRESSION_PATH for route in app_module.app.routes):
        return

    @app_module.app.get(REGRESSION_PATH)
    async def classifier_regressions():
        results = {}
        all_pass = True
        classifier_revision = None

        for fixture_id, fixture in app_module.DRY_RUN_FIXTURES.items():
            expected = fixture.get("expected_verification_status")
            if not expected:
                continue
            result = app_module._classify_claim(fixture["claim"], fixture["evidence_text"])
            actual = result["verification_status"]
            passed = actual == expected
            all_pass = all_pass and passed
            classifier_revision = (
                result.get("debug", {}).get("classifier_revision") or classifier_revision
            )
            results[fixture_id] = {
                "expected": expected,
                "actual": actual,
                "pass": passed,
                "verdict": result["verdict"],
                "confidence": result["confidence"],
            }

        return {
            "ok": all_pass,
            "service": "capi2 Claim Verify",
            "classifier_revision": classifier_revision,
            "fixture_count": len(results),
            "results": results,
        }
