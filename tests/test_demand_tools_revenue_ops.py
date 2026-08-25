import hashlib
import hmac
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from capi2.demand_tools import revenue_ops


class RevenueOpsTests(unittest.TestCase):
    def test_event_redacts_payer_and_extracts_settlement(self):
        ctx = SimpleNamespace(
            requirements={
                "resource": "https://capi2-demand-tools.onrender.com/v1/web/lookup",
                "network": "eip155:8453",
                "price": "$0.01",
            },
            payment_payload={"payload": {"authorization": {"from": "0xBuyerWallet"}}},
            result={"transaction": "0xabc"},
        )
        event = revenue_ops.settlement_event(ctx, "https://capi2-demand-tools.onrender.com")
        self.assertEqual(event["path"], "/v1/web/lookup")
        self.assertEqual(event["transaction_hash"], "0xabc")
        self.assertEqual(event["payer_ref"], "payer_" + hashlib.sha256(b"0xbuyerwallet").hexdigest()[:20])
        self.assertNotIn("0xBuyerWallet", json.dumps(event))
        self.assertEqual(event["id"], revenue_ops.settlement_event(ctx, "https://capi2-demand-tools.onrender.com")["id"])

    @patch("capi2.demand_tools.revenue_ops.urllib.request.urlopen")
    def test_delivery_is_signed_and_idempotent(self, urlopen: Mock):
        urlopen.return_value.__enter__.return_value.status = 202
        event = {"id": "evt_1", "type": "capi2.x402.settled"}
        with patch.dict(os.environ, {"CAPI2_REVENUE_WEBHOOK_SECRET": "secret"}, clear=False):
            revenue_ops._deliver("crm", "https://hooks.example.test/capi2", event)
        request = urlopen.call_args.args[0]
        expected = hmac.new(b"secret", request.data, hashlib.sha256).hexdigest()
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["idempotency-key"], "evt_1")
        self.assertEqual(headers["x-capi2-signature"], "sha256=" + expected)

    def test_no_targets_is_valid(self):
        with patch.dict(os.environ, {
            "CAPI2_LAGO_WEBHOOK_URL": "",
            "CAPI2_TRIGGER_WEBHOOK_URL": "",
            "CAPI2_CRM_WEBHOOK_URL": "",
        }, clear=False):
            self.assertEqual(revenue_ops._targets(), [("lago", ""), ("trigger", ""), ("crm", "")])


if __name__ == "__main__":
    unittest.main()
