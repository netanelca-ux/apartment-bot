from __future__ import annotations

"""
Facebook Marketplace scraper — GraphQL interception approach.
Intercepts Facebook's internal GraphQL API calls instead of relying on DOM selectors.
"""
import json
import logging
import re
from typing import Optional

from playwright.async_api import BrowserContext, Response

from config import SEARCH_CRITERIA

logger = logging.getLogger(__name__)

MARKETPLACE_URL = (
    "https://www.facebook.com/marketplace/108312912534207/rentals/"
    f"?maxPrice={SEARCH_CRITERIA['max_price']}"
    "&sortBy=creation_time_descend"
)


async def fetch_listings(context: BrowserContext) -> list[dict]:
    page = await context.new_page()
    raw_listings: dict[str, dict] = {}

    async def on_response(response: Response):
        if "graphql" not in response.url or response.status != 200:
            return
        try:
            body = await response.text()
            for line in body.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                    _extract_listings(parsed, raw_listings)
                except Exception:
                    pass
        except Exception:
            pass

    page.on("response", on_response)

    try:
        await page.goto(MARKETPLACE_URL, wait_until="domcontentloaded", timeout=40_000)

        if await page.query_selector('form[data-testid="royal_login_form"]'):
            logger.warning("Facebook Marketplace: login required — run tools/fb_login.py")
            return []

        await page.wait_for_timeout(2500)
        for _ in range(4):
            await page.evaluate("window.scrollBy(0, 2000)")
            await page.wait_for_timeout(1500)

        logger.debug(f"Marketplace: intercepted {len(raw_listings)} listings via GraphQL")

    except Exception as e:
        logger.error(f"Facebook Marketplace scraper error: {e}")
    finally:
        await page.close()

    results = []
    for listing_id, data in raw_listings.items():
        text = " ".join(filter(None, [
            data.get("title", ""),
            data.get("description", ""),
            data.get("location", ""),
        ]))

        if not _matches_neighborhoods(text):
            continue

        price = data.get("price", 0)
        if price and price > SEARCH_CRITERIA["max_price"]:
            continue

        results.append({
            "source": "facebook_marketplace",
            "listing_id": listing_id,
            "title": data.get("title", "")[:100],
            "price": price,
            "rooms": _extract_rooms(text),
            "neighborhood": _extract_neighborhood(text),
            "address": data.get("location", ""),
            "description": text[:500],
            "url": f"https://www.facebook.com/marketplace/item/{listing_id}/",
        })

    logger.info(f"Facebook Marketplace: {len(results)} relevant listings found")
    return results


# ── GraphQL parsers ───────────────────────────────────────────────────────────

def _extract_listings(data: dict, out: dict[str, dict]) -> None:
    """Try all known Marketplace GraphQL response shapes."""
    # Shape 1: marketplace_search.feed_units / feed_items
    for key in ("feed_units", "feed_items"):
        edges = _nested(data, "data", "marketplace_search", key, "edges")
        if isinstance(edges, list):
            for edge in edges:
                _parse_edge(edge, out)

    # Shape 2: viewer.marketplace_feed_stories
    edges = _nested(data, "data", "viewer", "marketplace_feed_stories", "edges")
    if isinstance(edges, list):
        for edge in edges:
            _parse_edge(edge, out)

    # Shape 3: city.marketplace_feed
    edges = _nested(data, "data", "city", "marketplace_feed", "edges")
    if isinstance(edges, list):
        for edge in edges:
            _parse_edge(edge, out)

    # Shape 4: top-level edges array
    edges = _nested(data, "data", "edges")
    if isinstance(edges, list):
        for edge in edges:
            _parse_edge(edge, out)


def _parse_edge(edge: dict, out: dict[str, dict]) -> None:
    if not isinstance(edge, dict):
        return
    node = edge.get("node", {})
    if not isinstance(node, dict):
        return

    listing = node.get("listing") or node
    if not isinstance(listing, dict):
        return

    listing_id = str(listing.get("id", "")).strip()
    if not listing_id:
        return

    if listing_id in out:
        return

    title = (
        listing.get("custom_title")
        or listing.get("name")
        or listing.get("marketplace_listing_title")
        or ""
    )

    price = _parse_price(listing)
    location = _parse_location(listing)
    description = _nested(listing, "description", "text") or ""

    out[listing_id] = {
        "title": title,
        "price": price,
        "location": location,
        "description": description,
    }


def _parse_price(listing: dict) -> int:
    for path in [
        ("listing_price", "amount"),
        ("price", "amount"),
        ("formatted_price",),
    ]:
        val = _nested(listing, *path)
        if val is not None:
            try:
                return int(float(str(val).replace(",", "").replace("₪", "").strip()))
            except (ValueError, TypeError):
                pass
    return 0


def _parse_location(listing: dict) -> str:
    rg = _nested(listing, "location", "reverse_geocode")
    if isinstance(rg, dict):
        parts = [
            _nested(rg, "neighborhood") or "",
            _nested(rg, "city") or (_nested(rg, "city_page", "display_name") or ""),
        ]
        return " ".join(p for p in parts if p).strip()

    loc = listing.get("location")
    if isinstance(loc, dict):
        return loc.get("city", "") or ""

    return ""


def _nested(obj: dict, *keys):
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


# ── text helpers ──────────────────────────────────────────────────────────────

def _matches_neighborhoods(text: str) -> bool:
    return any(n in text for n in SEARCH_CRITERIA["neighborhoods"])


def _extract_neighborhood(text: str) -> str:
    for n in SEARCH_CRITERIA["neighborhoods"]:
        if n in text:
            return n
    return ""


def _extract_rooms(text: str) -> Optional[float]:
    m = re.search(r"(\d[.,]?\d?)\s*חדר", text)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    return None
