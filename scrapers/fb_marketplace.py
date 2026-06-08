from __future__ import annotations

"""
Facebook Marketplace scraper — lightweight httpx approach via mbasic.facebook.com.
No browser required. Scrapes the mobile HTML version of Marketplace rentals.
"""
import logging
import re
from typing import Optional

from config import SEARCH_CRITERIA
from scrapers.fb_session import get_cookies, make_client

logger = logging.getLogger(__name__)

MARKETPLACE_URL = (
    "https://mbasic.facebook.com/marketplace/108312912534207/rentals/"
    f"?maxPrice={SEARCH_CRITERIA['max_price']}"
    "&sortBy=creation_time_descend"
)

OTHER_NEIGHBORHOODS = [
    "רמת אביב", "הצפון הישן", "הצפון החדש", "רמת החייל", "שכונת התקווה",
    "יד אליהו", "כפר שלם", "שפירא", "קריית שלום", "עזרא", "הארגזים",
    "רמת גן", "גבעתיים", "בני ברק", "חולון", "בת ים", "ראשון לציון",
    "פתח תקווה", "הרצליה", "רעננה",
]


async def fetch_listings(_ctx=None) -> list[dict]:
    cookies = get_cookies()
    if not cookies:
        logger.warning("No Facebook cookies — skipping Marketplace scan")
        return []

    async with make_client(cookies) as client:
        try:
            resp = await client.get(MARKETPLACE_URL)
        except Exception as e:
            logger.error(f"Facebook Marketplace request failed: {e}")
            return []

    if resp.status_code != 200:
        logger.warning(f"Marketplace: HTTP {resp.status_code}")
        return []

    if "login" in str(resp.url).lower() or 'id="login_form"' in resp.text:
        logger.warning("Facebook Marketplace: redirected to login — cookies expired")
        return []

    results = _parse_marketplace_listings(resp.text)
    logger.info(f"Facebook Marketplace: {len(results)} relevant listings found")
    return results


def _parse_marketplace_listings(html: str) -> list[dict]:
    results = []
    seen_ids: set[str] = set()

    # Marketplace item links: /marketplace/item/123456/
    item_re = re.compile(r'/marketplace/item/(\d+)/')
    ids = item_re.findall(html)

    if not ids:
        logger.debug("Marketplace: no item IDs found in HTML")
        return []

    # Split HTML around each item anchor to get per-listing context
    chunks = re.split(r'(?=/marketplace/item/\d+/)', html)

    for chunk in chunks:
        m = item_re.search(chunk)
        if not m:
            continue
        listing_id = m.group(1)
        if listing_id in seen_ids:
            continue
        seen_ids.add(listing_id)

        text = re.sub(r'<[^>]+>', ' ', chunk)
        text = re.sub(r'\s+', ' ', text).strip()

        if not text or len(text) < 10:
            continue

        # Skip listings from other neighborhoods
        if _has_other_neighborhood(text):
            continue

        price = _extract_price(text)
        if price and price > SEARCH_CRITERIA["max_price"]:
            continue

        neighborhood = _extract_neighborhood(text)
        # Only include if neighborhood matches or text has a known neighborhood
        if not neighborhood and not _matches_neighborhoods(text):
            continue

        results.append({
            "source": "facebook_marketplace",
            "listing_id": listing_id,
            "title": _extract_title(text),
            "price": price,
            "rooms": _extract_rooms(text),
            "neighborhood": neighborhood,
            "address": "",
            "description": text[:400],
            "published_at": None,
            "url": f"https://www.facebook.com/marketplace/item/{listing_id}/",
        })

    return results


def _matches_neighborhoods(text: str) -> bool:
    return any(n in text for n in SEARCH_CRITERIA["neighborhoods"])


def _extract_neighborhood(text: str) -> str:
    for n in SEARCH_CRITERIA["neighborhoods"]:
        if n in text:
            return n
    return ""


def _has_other_neighborhood(text: str) -> bool:
    return any(n in text for n in OTHER_NEIGHBORHOODS)


def _extract_price(text: str) -> int:
    patterns = [
        r"([\d,]+)\s*(?:₪|ש[\"']?ח|שקל|ש''ח)",
        r"(?:₪|מחיר:?)\s*([\d,]+)",
        r"\b([3-9]\d{3})\s*(?:כולל|לחודש|בחודש|₪|ש)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                val = int(m.group(1).replace(",", ""))
                if 1000 <= val <= 30000:
                    return val
            except ValueError:
                pass
    return 0


def _extract_rooms(text: str) -> Optional[float]:
    m = re.search(r"(\d[.,]?\d?)\s*חדר", text)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    return None


def _extract_title(text: str) -> str:
    first_line = text.split("\n")[0].strip()
    return first_line[:100] if first_line else text[:100]
