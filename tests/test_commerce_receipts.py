import base64
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SERVICE_DIR = Path(__file__).resolve().parents[1] / "capi2" / "x402_service"
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from commerce_receipts import issue_receipt, verify_receipt


class CommerceReceiptTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "request_id": "req_123",
            "idempotency_key": "checkout_123",
            "buyer_agent": "urn:agent:buyer-1",
            "seller": "https://seller.example/v1/report",
            "authority": {"decision": "authorized", "principal": "user"},
            "policy_decision": {"decision": "allow", "max_price_usd": 1.0},
            "price": 0.01,
            "asset": "USDC",
            "network": "eip155:8453",
            "request": {"claim": "A", "source": "https://example.com"},
            "delivery": {"verdict": "supported", "evidence": ["A"]},
            "verification": {"status": "supported", "confidence": 0.9},
            "settlement": {"transaction": "0xabc", "status": "settled"},
            "issued_at": "2026-09-01T12:00:00Z",
        }

    def test_issue_is_canonical_and_integrity_verifies(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CAPI2_RECEIPT_ED25519_SEED", None)
            receipt = issue_receipt(self.payload)
        result = verify_receipt(receipt)
        self.assertTrue(result["valid"])
        self.assertTrue(result["integrity_valid"])
        self.assertIsNone(result["signature_valid"])
        self.assertIn("receipt_unsigned", result["warnings"])
        self.assertNotEqual(receipt["request_sha256"], receipt["delivery_sha256"])

    def test_tampered_delivery_is_rejected(self):
        receipt = issue_receipt(self.payload)
        tampered = copy.deepcopy(receipt)
        tampered["delivery"]["verdict"] = "contradicted"
        result = verify_receipt(tampered)
        self.assertFalse(result["valid"])
        self.assertIn("delivery_sha256_mismatch", result["warnings"])

    def test_optional_ed25519_signature_verifies(self):
        seed = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode()
        with patch.dict(os.environ, {"CAPI2_RECEIPT_ED25519_SEED": seed}):
            receipt = issue_receipt(self.payload)
        result = verify_receipt(receipt)
        self.assertTrue(result["valid"])
        self.assertTrue(result["signature_valid"])

    def test_receipt_id_is_idempotent_for_same_commercial_payload(self):
        first = issue_receipt(self.payload)
        changed_time = {**self.payload, "issued_at": "2026-09-01T13:00:00Z"}
        second = issue_receipt(changed_time)
        self.assertEqual(first["receipt_id"], second["receipt_id"])


if __name__ == "__main__":
    unittest.main()
