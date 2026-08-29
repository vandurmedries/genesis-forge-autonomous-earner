import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SERVICE_DIR = Path(__file__).resolve().parents[1] / "capi2" / "x402_service"
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

try:
    from fastapi.testclient import TestClient
    from x402.schemas.hooks import ResourceVerifyResponse
    from x402.schemas.responses import SettleResponse, VerifyResponse

    import app as service_module
    import bootstrap
except ImportError as exc:  # The base developer environment intentionally has no x402 SDK.
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


@unittest.skipIf(IMPORT_ERROR is not None, f"x402 contract dependencies unavailable: {IMPORT_ERROR}")
class PaidLoopContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(bootstrap.app)
        self.request_body = {
            "vendor_url": "https://example.com/security",
            "claim": "Customer data is encrypted at rest.",
        }

    @staticmethod
    def _decode_header(value):
        return json.loads(base64.b64decode(value).decode())

    def test_discovery_challenge_paid_retry_and_settlement_response(self):
        discovery = self.client.get("/.well-known/x402")
        self.assertEqual(discovery.status_code, 200)
        self.assertIn("resources", discovery.json())

        unpaid = self.client.post("/v1/claim-verify", json=self.request_body)
        self.assertEqual(unpaid.status_code, 402)
        challenge = self._decode_header(unpaid.headers["payment-required"])
        self.assertEqual(challenge["x402Version"], 2)
        self.assertEqual(challenge["accepts"][0]["network"], "eip155:8453")
        self.assertEqual(challenge["accepts"][0]["amount"], "10000")

        payment_payload = {
            "x402Version": 2,
            "payload": {
                "signature": "0xtest",
                "authorization": {"from": "0x1111111111111111111111111111111111111111"},
            },
            "accepted": challenge["accepts"][0],
        }
        payment_header = base64.b64encode(
            json.dumps(payment_payload, separators=(",", ":")).encode()
        ).decode()
        verify_result = ResourceVerifyResponse(
            VerifyResponse(
                is_valid=True,
                payer="0x1111111111111111111111111111111111111111",
            )
        )
        settle_result = SettleResponse(
            success=True,
            payer="0x1111111111111111111111111111111111111111",
            transaction="0xabc",
            network="eip155:8453",
            amount="10000",
        )
        evidence_page = (
            "Security documentation. Customer data is encrypted at rest using industry "
            "standard encryption. Access is restricted and audited. This page describes "
            "controls for enterprise customers and procurement reviewers."
        )

        with (
            patch.object(service_module.server, "verify_payment", return_value=verify_result) as verify,
            patch.object(service_module.server, "settle_payment", return_value=settle_result) as settle,
            patch.object(
                service_module,
                "_fetch_public_source",
                return_value=("https://example.com/security", f"<p>{evidence_page}</p>"),
            ),
        ):
            paid = self.client.post(
                "/v1/claim-verify",
                headers={"PAYMENT-SIGNATURE": payment_header},
                json=self.request_body,
            )

        self.assertEqual(paid.status_code, 200)
        self.assertEqual(paid.json()["verification_status"], "supported")
        receipt = self._decode_header(paid.headers["payment-response"])
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["transaction"], "0xabc")
        verify.assert_called_once()
        settle.assert_called_once()
        self.assertTrue(service_module.server._capi2_settlement_observer)

    def test_vendor_risk_pack_is_discoverable_and_challenges_for_four_cents(self):
        pack = {"claims": [self.request_body, self.request_body]}

        validation = self.client.post("/v1/vendor-risk-pack/validate", json=pack)
        self.assertEqual(validation.status_code, 200)
        self.assertTrue(validation.json()["valid"])
        self.assertEqual(validation.json()["price"], "$0.04")

        catalog = self.client.get("/v1/buyer-catalog")
        resources = {item["path"]: item for item in catalog.json()["resources"]}
        self.assertIn("/v1/vendor-risk-pack", resources)

        unpaid = self.client.post("/v1/vendor-risk-pack", json=pack)
        self.assertEqual(unpaid.status_code, 402)
        challenge = self._decode_header(unpaid.headers["payment-required"])
        self.assertEqual(challenge["x402Version"], 2)
        self.assertEqual(challenge["accepts"][0]["network"], "eip155:8453")
        self.assertEqual(challenge["accepts"][0]["amount"], "40000")


if __name__ == "__main__":
    unittest.main()
