import importlib.util
import pathlib
import unittest
from unittest.mock import Mock, patch


MODULE_PATH = pathlib.Path(__file__).parents[1] / "ops" / "payan_onboard.py"
SPEC = importlib.util.spec_from_file_location("payan_onboard", MODULE_PATH)
payan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(payan)


class CapabilityMatchingTests(unittest.TestCase):
    def test_incidental_benchmark_hash_does_not_match(self):
        self.assertIsNone(
            payan.detect_capability(
                "Independent solver for funded MCP commerce child",
                "Implement a Node CLI. Benchmark digest sha256:abc123. Coordination only.",
            )
        )

    def test_explicit_sha256_title_matches(self):
        self.assertEqual(
            payan.detect_capability("Compute SHA-256 for this text", "Return the digest."),
            "sha256",
        )

    def test_catalog_health_bounty_matches_without_input(self):
        capability = payan.detect_capability(
            "Build a catalog endpoint-health checker (find dead ecosystem sellers)",
            "Probe top offers without paid calls.",
        )
        self.assertEqual(capability, "catalog_health")
        self.assertTrue(payan.has_solvable_input({}, capability))

    def test_coordination_request_is_blocked(self):
        self.assertIsNone(
            payan.detect_capability(
                "SHA-256 collaborator",
                "This unescrowed request is collaborator discovery only and separately funded.",
            )
        )

    def test_requires_input_that_can_be_solved(self):
        self.assertFalse(payan.has_solvable_input({}, "sha256"))
        self.assertFalse(payan.has_solvable_input({"inputPayload": '{"url":"x"}'}, "sha256"))
        self.assertTrue(payan.has_solvable_input({"inputPayload": '{"text":"hello"}'}, "sha256"))

    @patch.object(payan.requests, "get")
    def test_duplicate_wallet_bid_is_detected_across_agent_ids(self, get):
        request_response = Mock(ok=True)
        request_response.json.return_value = {"bids": [{"bidderId": "duplicate-agent"}]}
        agent_response = Mock(ok=True)
        agent_response.json.return_value = {"walletAddress": payan.WALLET.lower()}
        get.side_effect = [request_response, agent_response]

        self.assertTrue(payan.already_bid_remotely("request-1"))

    @patch.object(payan.requests, "post")
    def test_registration_fails_closed_without_configured_identity(self, post):
        old_key = payan.api_key
        old_allow = payan.ALLOW_PROVIDER_REGISTRATION
        try:
            payan.api_key = None
            payan.ALLOW_PROVIDER_REGISTRATION = False
            with self.assertRaisesRegex(RuntimeError, "provider_identity_missing"):
                payan.register_provider()
            post.assert_not_called()
        finally:
            payan.api_key = old_key
            payan.ALLOW_PROVIDER_REGISTRATION = old_allow


if __name__ == "__main__":
    unittest.main()
