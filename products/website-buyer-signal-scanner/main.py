"""Apify entry point for Website Buyer Signal Scanner."""

from __future__ import annotations

import asyncio
from typing import Any

from apify import Actor

from scanner import scan_website


def _inputs(actor_input: dict[str, Any]) -> list[str]:
    values = actor_input.get("startUrls") or []
    urls = [item.get("url") if isinstance(item, dict) else item for item in values]
    urls.extend(actor_input.get("domains") or [])
    return list(dict.fromkeys(str(url).strip() for url in urls if url and str(url).strip()))[:100]


async def main() -> None:
    async with Actor:
        actor_input = await Actor.get_input() or {}
        urls = _inputs(actor_input)
        if not urls:
            raise ValueError("Provide at least one start URL or domain.")
        include_contacts = bool(actor_input.get("includeContacts", True))
        for url in urls:
            try:
                result = await asyncio.to_thread(scan_website, url, include_contacts)
            except Exception as exc:
                Actor.log.warning("Skipped %s: %s", url, exc)
                continue
            result["status"] = "completed"
            result["billable_event"] = "apify-default-dataset-item"
            await Actor.push_data(result)
            Actor.log.info("Scanned and stored %s", url)


if __name__ == "__main__":
    asyncio.run(main())
