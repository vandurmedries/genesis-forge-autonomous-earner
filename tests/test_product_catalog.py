import unittest
from decimal import Decimal

from capi2.product_catalog import products


class ProductCatalogTests(unittest.TestCase):
    def test_rarebrief_products_are_normalized(self):
        catalog = products()
        self.assertEqual(len(catalog), 5)
        self.assertEqual(
            {item["product_id"] for item in catalog},
            {
                "rarebrief.offer-economics",
                "rarebrief.price-floor",
                "rarebrief.offer-packager",
                "rarebrief.lead-priority",
                "rarebrief.senti-watch",
            },
        )
        self.assertTrue(all(item["source"]["network"] == "eip155:8453" for item in catalog))
        self.assertTrue(all(Decimal(item["price_usd"]) > 0 for item in catalog))

    def test_catalog_has_one_recurring_capability_and_unique_routes(self):
        catalog = products()
        watches = [item for item in catalog if item["revenue_model"] == "time_limited_watch"]
        self.assertEqual([item["product_id"] for item in watches], ["rarebrief.senti-watch"])
        routes = {(item["method"], item["path"]) for item in catalog}
        self.assertEqual(len(routes), len(catalog))

    def test_every_product_emits_the_canonical_revenue_event(self):
        for product in products():
            contract = product["revenue_contract"]
            self.assertEqual(contract["event_type"], "capi2.x402.settled")
            self.assertIn("transaction_hash", contract["required_fields"])
            self.assertEqual(contract["payer_storage"], "one-way reference only")


if __name__ == "__main__":
    unittest.main()
