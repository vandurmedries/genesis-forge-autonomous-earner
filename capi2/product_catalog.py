"""Canonical, read-only CAPI2 product catalog loaders and guards."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


CATALOG_DIR = Path(__file__).with_name("catalog")


class CatalogError(ValueError):
    pass


def _validate_manifest(manifest: dict[str, Any], source: Path) -> None:
    if manifest.get("schema_version") != "capi2.product_catalog/1.0":
        raise CatalogError(f"unsupported catalog schema: {source}")
    products = manifest.get("products")
    if not isinstance(products, list) or not products:
        raise CatalogError(f"catalog has no products: {source}")
    network = manifest.get("source", {}).get("network")
    if network != "eip155:8453":
        raise CatalogError(f"catalog must settle on Base: {source}")
    for product in products:
        required = {
            "product_id", "operation_id", "name", "method", "path",
            "price_usd", "revenue_model", "buyer_job", "input_schema",
        }
        missing = required.difference(product)
        if missing:
            raise CatalogError(f"{source}: {product.get('product_id')} missing {sorted(missing)}")
        try:
            price = Decimal(product["price_usd"])
        except (InvalidOperation, TypeError) as exc:
            raise CatalogError(f"invalid price for {product['product_id']}") from exc
        if price <= 0:
            raise CatalogError(f"non-positive price for {product['product_id']}")
        if product["method"] not in {"GET", "POST"} or not product["path"].startswith("/"):
            raise CatalogError(f"invalid route for {product['product_id']}")


def load_manifests(paths: Iterable[Path] | None = None) -> list[dict[str, Any]]:
    selected = sorted(paths or CATALOG_DIR.glob("*.json"))
    manifests = [json.loads(path.read_text()) for path in selected]
    for manifest, path in zip(manifests, selected):
        _validate_manifest(manifest, path)
    return manifests


def products() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_routes: set[tuple[str, str]] = set()
    for manifest in load_manifests():
        source = manifest["source"]
        revenue_contract = manifest["revenue_contract"]
        for raw in manifest["products"]:
            product = {**raw, "source": source, "revenue_contract": revenue_contract}
            route = (product["method"], product["path"])
            if product["product_id"] in seen_ids:
                raise CatalogError(f"duplicate product id: {product['product_id']}")
            if route in seen_routes:
                raise CatalogError(f"duplicate product route: {route}")
            seen_ids.add(product["product_id"])
            seen_routes.add(route)
            result.append(product)
    return result
