from __future__ import annotations

import json
import logging
from typing import Optional

from config import SEARCH_CRITERIA

logger = logging.getLogger(__name__)

BASE_URL = (
    "https://www.yad2.co.il/realestate/rent"
    "?city=5000"
    f"&minPrice={SEARCH_CRITERIA['min_price']}"
    f"&maxPrice={SEARCH_CRITERIA['max_price']}"
    "&minRooms=1.5"
    "&maxRooms=5"
)

MAX_PAGES = 3


async def fetch_listings(browser=None) -> list[dict]:
    from scrapers.browser import managed_browser, new_page as _new_page

    async def _run(b):
        page = await _new_page(b)
        results = []
        try:
            for page_num in range(1, MAX_PAGES + 1):
                url = BASE_URL if page_num == 1 else f"{BASE_URL}&page={page_num}"
                page_results = await _fetch_page(page, url, page_num)
                if not page_results:
                    break
                results.extend(page_results)
        finally:
            await page.context.close()
        logger.info(f"Yad2: {len(results)} relevant listings found")
        return results

    if browser is not None:
        return await _run(browser)
    async with managed_browser() as b:
        return await _run(b)


async def _fetch_page(page, url: str, page_num: int) -> list[dict]:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except Exception as e:
        logger.warning(f"Yad2 page {page_num}: navigation failed: {e}")
        return []

    try:
        data_text: str = await page.evaluate(
            "document.getElementById('__NEXT_DATA__')?.textContent || ''"
        )
    except Exception as e:
        logger.warning(f"Yad2 page {page_num}: JS eval failed: {e}")
        return []

    if not data_text:
        logger.warning(f"Yad2 page {page_num}: no __NEXT_DATA__ found")
        return []

    try:
        data = json.loads(data_text)
    except Exception as e:
        logger.warning(f"Yad2 page {page_num}: JSON parse error: {e}")
        return []

    feed = data.get("props", {}).get("pageProps", {}).get("feed", {})
    all_items = feed.get("private", []) + feed.get("agency", [])

    results = []
    for item in all_items:
        listing = _parse_item(item)
        if listing:
            results.append(listing)

    logger.debug(f"Yad2 page {page_num}: {len(results)} relevant / {len(all_items)} total")
    return results


def _parse_item(item: dict) -> Optional[dict]:
    token = item.get("token", "")
    if not token:
        return None

    price = item.get("price", 0) or 0
    if price and price > SEARCH_CRITERIA["max_price"]:
        return None
    if price and price < SEARCH_CRITERIA.get("min_price", 0):
        return None

    addr = item.get("address", {})
    neighborhood_raw = addr.get("neighborhood", {}).get("text", "")
    neighborhood_match = _match_neighborhood(neighborhood_raw)
    if not neighborhood_match:
        return None

    details = item.get("additionalDetails", {})
    rooms = details.get("roomsCount")
    broker = item.get("adType", "") == "agency"

    street_raw = addr.get("street", {}).get("text", "")
    house_num = addr.get("house", {}).get("number", "")
    city_raw = addr.get("city", {}).get("text", "")
    address = " ".join(p for p in [street_raw, str(house_num) if house_num else ""] if p)

    return {
        "source": "yad2",
        "listing_id": token,
        "title": _build_title(neighborhood_match, rooms, price),
        "price": price,
        "rooms": float(rooms) if rooms else None,
        "neighborhood": neighborhood_match,
        "address": address,
        "description": f"{neighborhood_raw} | {address} | {city_raw}",
        "published_at": None,
        "broker": broker,
        "url": f"https://www.yad2.co.il/item/{token}",
    }


def _match_neighborhood(text: str) -> str:
    for n in SEARCH_CRITERIA["neighborhoods"]:
        if n in text:
            return n
    return ""


def _build_title(neighborhood: str, rooms: Optional[float], price: int) -> str:
    parts = [neighborhood]
    if rooms:
        parts.append(f"{rooms} חדרים")
    if price:
        parts.append(f"₪{price:,}")
    return " | ".join(parts)
