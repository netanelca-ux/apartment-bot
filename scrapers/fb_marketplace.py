from __future__ import annotations

"""
Facebook Marketplace scraper.
Navigates to the Tel Aviv rentals page and extracts listings matching criteria.
Requires a saved Facebook session (run tools/fb_login.py first).
"""
import logging
import re

from playwright.async_api import BrowserContext

from config import SEARCH_CRITERIA

logger = logging.getLogger(__name__)

# Tel Aviv city ID on Facebook Marketplace
MARKETPLACE_URL = (
    "https://www.facebook.com/marketplace/108312912534207/rentals/"
    f"?maxPrice={SEARCH_CRITERIA['max_price']}"
    "&sortBy=creation_time_descend"
)


async def fetch_listings(context: BrowserContext) -> list[dict]:
    page = await context.new_page()
    results = []

    try:
        await page.goto(MARKETPLACE_URL, wait_until="domcontentloaded", timeout=40_000)

        # Wait for listing cards to appear
        try:
            await page.wait_for_selector('a[href*="/marketplace/item/"]', timeout=20_000)
        except Exception:
            logger.warning("Facebook Marketplace: no listing cards found (might need login)")
            await page.screenshot(path="data/debug_marketplace.png")
            return []

        # Scroll once to load more listings
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(2000)

        cards = await page.evaluate("""
            () => {
                const anchors = document.querySelectorAll('a[href*="/marketplace/item/"]');
                const seen = new Set();
                return Array.from(anchors)
                    .map(a => {
                        const card = a.closest('[class]') || a;
                        const text = card.innerText || a.innerText || '';
                        const href = a.href;
                        const id = href.match(/\\/marketplace\\/item\\/(\\d+)/)?.[1] || '';
                        return { href, text, id };
                    })
                    .filter(({ id }) => {
                        if (!id || seen.has(id)) return false;
                        seen.add(id);
                        return true;
                    });
            }
        """)

        for card in cards:
            text = card.get("text", "")
            href = card.get("href", "")
            listing_id = card.get("id", "")

            if not listing_id:
                continue

            # Filter by neighborhood keywords
            if not _matches_neighborhoods(text):
                continue

            # Skip posts from people searching (not listing)
            if _is_search_request(text):
                continue

            price = _extract_price(text)
            if price and price > SEARCH_CRITERIA["max_price"]:
                continue

            results.append({
                "source": "facebook_marketplace",
                "listing_id": listing_id,
                "title": text.split("\n")[0][:100],
                "price": price,
                "rooms": _extract_rooms(text),
                "neighborhood": _extract_neighborhood(text),
                "address": _extract_address(text),
                "description": text[:500],
                "url": href.split("?")[0],
            })

    except Exception as e:
        logger.error(f"Facebook Marketplace scraper error: {e}")
    finally:
        await page.close()

    logger.info(f"Facebook Marketplace: {len(results)} relevant listings found")
    return results


def _matches_neighborhoods(text: str) -> bool:
    return any(n in text for n in SEARCH_CRITERIA["neighborhoods"])


def _extract_neighborhood(text: str) -> str:
    for n in SEARCH_CRITERIA["neighborhoods"]:
        if n in text:
            return n
    return ""


def _extract_price(text: str) -> int:
    patterns = [
        r"([\d,]+)\s*(?:₪|ש[\"']?ח|שקל)",   # "7,200 ₪"
        r"(?:₪|ש[\"']?ח)\s*([\d,]+)",          # "₪ 7,200"
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            val = int(m.group(1).replace(",", ""))
            if 1000 <= val <= 30000:
                return val
    return 0


def _extract_rooms(text: str) -> float | None:
    m = re.search(r"(\d[.,]?\d?)\s*חדר", text)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    return None


def _extract_address(text: str) -> str:
    """Extract street/address line — Marketplace cards often show it as a separate line."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines:
        # Skip price lines, room lines, and very short lines
        if re.search(r"₪|שח|שקל|חדר|להשכרה|לשכירות", line):
            continue
        if re.search(r"[א-ת]{2,}", line) and len(line) > 5:
            return line[:80]
    return ""


def _is_search_request(text: str) -> bool:
    request_keywords = ["מחפש", "מחפשת", "רצוי", "ישנה הצעה", "מישהו מכיר"]
    return any(kw in text for kw in request_keywords)
