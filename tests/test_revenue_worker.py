import importlib
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


class RevenueWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        os.environ["CAPI2_REVENUE_WORKER_TOKEN"] = "test-secret"
        module_path = Path(__file__).parents[1] / "capi2" / "x402_service" / "revenue_worker.py"
        spec = importlib.util.spec_from_file_location("capi2_revenue_worker_test", module_path)
        self.module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(self.module)
        app = FastAPI()
        self.module.install(app)
        self.client = TestClient(app)

    def tearDown(self):
        self.tempdir.cleanup()
        os.environ.pop("CAPI2_REVENUE_WORKER_TOKEN", None)

    def test_requires_bearer_token(self):
        self.assertEqual(self.client.post("/v1/internal/revenue-cycle").status_code, 401)

    def test_cycle_records_sanitized_state(self):
        payloads = [
            {"ok": True},
            {"resources": [{}, {}]},
            {"offers": [{}, {}, {}]},
        ]
        with patch.object(self.module, "_get_json", side_effect=payloads), patch.object(self.module, "_persist_run", return_value=41):
            response = self.client.post(
                "/v1/internal/revenue-cycle",
                headers={"authorization": "Bearer test-secret"},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["discoveryResources"], 2)
        self.assertEqual(body["marketSignals"], 3)
        self.assertEqual(body["verifiedBuyerLeads"], 0)
        self.assertEqual(body["actionsAutoApproved"], 1)
        self.assertEqual(body["organicRevenueCents"], 0)
        self.assertEqual(body["salesBot"]["objective"], "attract_verified_preview_users")
        with patch.object(self.module, "_latest_run", return_value={"runId": 41, "ok": True}):
            status = self.client.get("/v1/revenue-worker/status").json()
        self.assertTrue(status["configured"])
        self.assertEqual(status["lastRun"]["runId"], 41)

    def test_sales_bot_exposes_product_ladder_and_guardrails(self):
        manifest = self.client.get("/v1/sales-bot")
        self.assertEqual(manifest.status_code, 200)
        body = manifest.json()
        self.assertEqual(body["mission"], "sell, measure, learn, repeat")
        self.assertEqual(body["productLadder"][1]["priceUsd"], 29)
        self.assertIn("no spam", body["guardrails"])

    def test_sales_bot_cycle_requires_authentication(self):
        self.assertEqual(self.client.post("/v1/internal/sales-bot/cycle").status_code, 401)


if __name__ == "__main__":
    unittest.main()
