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
    f"&minBedrooms={SEARCH_CRITERIA['rooms']}"
    f"&maxBedrooms={SEARCH_CRITERIA['rooms']}"
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
                "rooms": SEARCH_CRITERIA["rooms"],
                "neighborhood": _extract_neighborhood(text),
                "address": "",
                "description": text[:400],
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
    match = re.search(r"([\d,]+)\s*(?:₪|ש[\"']?ח|שקל)", text)
    if match:
        return int(match.group(1).replace(",", ""))
    return 0


def _is_search_request(text: str) -> bool:
    request_keywords = ["מחפש", "מחפשת", "רצוי", "ישנה הצעה", "מישהו מכיר"]
    return any(kw in text for kw in request_keywords)
