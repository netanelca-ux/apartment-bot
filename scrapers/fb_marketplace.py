from __future__ import annotations

import logging
import re
from typing import Optional

from config import SEARCH_CRITERIA
from scrapers.fb_session import get_cookies

logger = logging.getLogger(__name__)

MARKETPLACE_URL = (
    "https://www.facebook.com/marketplace/108312912534207/rentals/"
    f"?maxPrice={SEARCH_CRITERIA['max_price']}&sortBy=creation_time_descend"
)

OTHER_NEIGHBORHOODS = [
    "רמת אביב", "הצפון הישן", "הצפון החדש", "רמת החייל", "שכונת התקווה",
    "יד אליהו", "כפר שלם", "שפירא", "קריית שלום", "עזרא", "הארגזים",
    "רמת גן", "גבעתיים", "בני ברק", "חולון", "בת ים", "ראשון לציון",
    "פתח תקווה", "הרצליה", "רעננה",
]

# Extract unique marketplace items: id, text, href
_EXTRACT_JS = """
() => {
    const seen = new Set();
    const items = [];
    document.querySelectorAll('a[href*="/marketplace/item/"]').forEach(el => {
        const m = el.href.match(/marketplace\\/item\\/(\\d+)/);
        if (!m || seen.has(m[1])) return;
        seen.add(m[1]);
        const container = el.closest('[role="listitem"]') || el.parentElement || el;
        items.push({id: m[1], text: container.innerText, href: el.href});
    });
    return items;
}
"""


async def fetch_listings(browser=None) -> list[dict]:
    from scrapers.browser import managed_browser, new_page as _new_page

    cookies = get_cookies()
    if not cookies:
        logger.warning("No Facebook cookies — skipping Marketplace scan")
        return []

    fb_cookies = [
        {"name": k, "value": v, "domain": ".facebook.com", "path": "/"}
        for k, v in cookies.items()
    ]

    async def _run(b):
        page = await _new_page(b, cookies=fb_cookies)
        results = []
        try:
            try:
                await page.goto(MARKETPLACE_URL, wait_until="domcontentloaded", timeout=30_000)
            except Exception as e:
                logger.error(f"Facebook Marketplace: navigation failed: {e}")
                return []

            current_url = page.url
            if "login" in current_url or "checkpoint" in current_url:
                logger.warning(f"Marketplace: session issue — redirected to {current_url}")
                return []

            # Wait for listing cards
            try:
                await page.wait_for_selector('a[href*="/marketplace/item/"]', timeout=10_000)
            except Exception:
                pass

            try:
                items_data: list[dict] = await page.evaluate(_EXTRACT_JS)
            except Exception as e:
                logger.warning(f"Marketplace: JS evaluation failed: {e}")
                return []

            for item in items_data:
                listing = _parse_item(item)
                if listing:
                    results.append(listing)
        finally:
            await page.context.close()

        logger.info(f"Facebook Marketplace: {len(results)} relevant listings found")
        return results

    if browser is not None:
        return await _run(browser)
    async with managed_browser() as b:
        return await _run(b)


def _parse_item(item: dict) -> Optional[dict]:
    listing_id = item.get("id", "")
    text = item.get("text", "")

    if not listing_id or not text:
        return None

    if _has_other_neighborhood(text):
        return None

    price = _extract_price(text)
    if price and price > SEARCH_CRITERIA["max_price"]:
        return None

    neighborhood = _extract_neighborhood(text)
    if not neighborhood and not _matches_neighborhoods(text):
        return None

    return {
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
    }


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
