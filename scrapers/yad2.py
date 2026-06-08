from __future__ import annotations

"""
Yad2 scraper — reads the __NEXT_DATA__ JSON embedded in the page.
No browser required. HTTP/2 + full browser headers bypass ShieldSquare.
"""
import json
import logging
import re
from typing import Optional

from curl_cffi.requests import AsyncSession

from config import SEARCH_CRITERIA

logger = logging.getLogger(__name__)

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

BASE_URL = (
    "https://www.yad2.co.il/realestate/rent"
    "?city=5000"
    f"&minPrice={SEARCH_CRITERIA['min_price']}"
    f"&maxPrice={SEARCH_CRITERIA['max_price']}"
    "&minRooms=1.5"
    "&maxRooms=5"
)

MAX_PAGES = 3


async def fetch_listings(_ctx=None) -> list[dict]:
    results: list[dict] = []
    try:
        async with AsyncSession(impersonate="chrome124", headers=HEADERS) as client:
            for page in range(1, MAX_PAGES + 1):
                url = BASE_URL if page == 1 else f"{BASE_URL}&page={page}"
                page_results = await _fetch_page(client, url, page)
                if not page_results:
                    break
                results.extend(page_results)
    except Exception as e:
        logger.error(f"Yad2 scraper error: {e}")

    logger.info(f"Yad2: {len(results)} relevant listings found")
    return results


async def _fetch_page(client: AsyncSession, url: str, page: int) -> list[dict]:
    try:
        resp = await client.get(url)
    except Exception as e:
        logger.warning(f"Yad2 page {page}: request failed: {e}")
        return []

    if resp.status_code != 200:
        logger.warning(f"Yad2 page {page}: HTTP {resp.status_code}")
        return []

    if "ShieldSquare" in resp.text or "captcha" in resp.text.lower():
        logger.warning(f"Yad2 page {page}: blocked by bot detection")
        return []

    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.DOTALL)
    if not m:
        logger.warning(f"Yad2 page {page}: no __NEXT_DATA__ found")
        return []

    try:
        data = json.loads(m.group(1))
    except Exception as e:
        logger.warning(f"Yad2 page {page}: JSON parse error: {e}")
        return []

    feed = data.get("props", {}).get("pageProps", {}).get("feed", {})
    private_items = feed.get("private", [])
    agency_items = feed.get("agency", [])
    all_items = private_items + agency_items

    results = []
    for item in all_items:
        listing = _parse_item(item)
        if listing:
            results.append(listing)

    logger.debug(f"Yad2 page {page}: {len(results)} relevant / {len(all_items)} total")
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
    city_raw = addr.get("city", {}).get("text", "")
    street_raw = addr.get("street", {}).get("text", "")
    house_num = addr.get("house", {}).get("number", "")

    neighborhood_match = _match_neighborhood(neighborhood_raw)
    if not neighborhood_match:
        return None

    details = item.get("additionalDetails", {})
    rooms = details.get("roomsCount")

    ad_type = item.get("adType", "")
    broker = ad_type == "agency"

    address_parts = [p for p in [street_raw, str(house_num) if house_num else ""] if p]
    address = " ".join(address_parts)

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
