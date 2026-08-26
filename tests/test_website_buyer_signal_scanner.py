import importlib.util
import pathlib
import unittest
from unittest.mock import patch

MODULE_PATH = pathlib.Path(__file__).parents[1] / "products" / "website-buyer-signal-scanner" / "scanner.py"
SPEC = importlib.util.spec_from_file_location("buyer_signal_scanner", MODULE_PATH)
scanner = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(scanner)


class ScannerTests(unittest.TestCase):
    def test_normalizes_plain_domain(self):
        self.assertEqual(scanner.normalize_url("example.com"), "https://example.com")

    @patch.object(scanner, "fetch_public_html")
    def test_extracts_stack_contacts_and_signals(self, fetch):
        fetch.return_value = {
            "final_url": "https://shop.example.com/",
            "status_code": 200,
            "headers": {"server": "nginx"},
            "html": """<html><head><title>Shop</title><meta name='generator' content='WordPress 6'>
            <script src='https://cdn.shopify.com/a.js'></script></head><body>
            <a href='mailto:sales@example.com'>Email</a><a href='/contact'>Contact</a>
            <a href='https://linkedin.com/company/example'>LinkedIn</a></body></html>""",
        }
        result = scanner.scan_website("shop.example.com")
        self.assertIn("Shopify", result["technologies"])
        self.assertIn("WordPress", result["technologies"])
        self.assertEqual(result["contacts"]["emails"], ["sales@example.com"])
        self.assertIn("linkedin", result["contacts"]["socials"])
        self.assertTrue(any(item["signal"] == "analytics_not_detected" for item in result["buyer_signals"]))


if __name__ == "__main__":
    unittest.main()
