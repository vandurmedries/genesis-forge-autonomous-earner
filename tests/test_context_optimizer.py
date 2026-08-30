import unittest
from unittest.mock import patch

from capi2.demand_tools import app as module


class ContextOptimizerTests(unittest.TestCase):
    def setUp(self):
        module._CONTEXT_CACHE.clear()
        self.payload = module.ContextOptimizerRequest(
            url="https://example.com/live",
            query="temperature",
            cache_ttl_seconds=300,
            max_output_chars=200,
        )
        self.fetched = {
            "requested_url": "https://example.com/live",
            "final_url": "https://example.com/live",
            "status": 200,
            "content_type": "application/json",
            "headers": {},
            "raw": b'{"temperature":21,"status":"ok"}',
            "text": '{"temperature":21,"status":"ok"}',
        }

    def test_cache_and_unchanged_digest_reduce_repeated_context(self):
        with patch.object(module, "_safe_fetch", return_value=self.fetched) as fetch:
            first = module.context_optimizer(self.payload)
            second_payload = self.payload.model_copy(update={"previous_sha256": first["sha256"]})
            second = module.context_optimizer(second_payload)

        fetch.assert_called_once()
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["compact_text"], "")
        self.assertTrue(second["usage"]["network_fetch_avoided"])
        self.assertGreater(second["usage"]["estimated_context_tokens_avoided"], 0)
        self.assertFalse(second["energy_model"]["guaranteed"])


if __name__ == "__main__":
    unittest.main()
