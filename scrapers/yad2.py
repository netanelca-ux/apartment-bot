"""
Yad2 scraper using Playwright.
Navigates to the search page, intercepts the JSON feed, and parses listings.
Falls back to DOM parsing if the API interception fails.
"""
import logging
import re

from playwright.async_api import BrowserContext

from config import SEARCH_CRITERIA

logger = logging.getLogger(__name__)

SEARCH_URL = (
    "https://www.yad2.co.il/realestate/rent"
    "?topArea=2&city=5000"
    f"&price=0-{SEARCH_CRITERIA['max_price']}"
    "&priceType=monthly"
)

# Fallback URL without price filter (in case Yad2 changed params)
SEARCH_URL_FALLBACK = "https://www.yad2.co.il/realestate/rent?topArea=2&city=5000"

# DOM selectors to try in order
_LINK_SELECTORS = [
    'a[href*="/realestate/item/"]',
    'a[href*="/item/"]',
    '[data-item-id] a',
    'article a[href*="yad2"]',
]


async def fetch_listings(context: BrowserContext) -> list[dict]:
    page = await context.new_page()
    api_items: list = []
    seen_urls: list[str] = []

    async def capture_json_feed(response):
        if response.status != 200:
            return
        ct = response.headers.get("content-type", "")
        if "json" not in ct:
            return
        url = response.url
        try:
            data = await response.json()
            items = (
                data.get("feed", {}).get("feed_items", [])
                or data.get("data", {}).get("feed", {}).get("feed_items", [])
                or data.get("items", [])
            )
            if items:
                api_items.extend(items)
                logger.info(f"Yad2: captured {len(items)} items from {url}")
            elif "yad2" in url and ("feed" in str(data) or "items" in str(data)[:200]):
                seen_urls.append(url)
        except Exception:
            pass

    page.on("response", capture_json_feed)

    try:
        await page.goto(SEARCH_URL, wait_until="networkidle", timeout=45_000)
        await page.wait_for_timeout(3000)
    except Exception as e:
        logger.error(f"Yad2: page load failed: {e}")
        await page.close()
        return []
    finally:
        page.remove_listener("response", capture_json_feed)

    if api_items:
        results = _parse_api_items(api_items)
    else:
        if seen_urls:
            logger.info(f"Yad2: JSON responses seen but no feed_items. URLs: {seen_urls[:3]}")
        logger.info("Yad2: API interception yielded nothing, falling back to DOM parsing")
        results = await _parse_dom(page)

    await page.close()
    logger.info(f"Yad2: {len(results)} relevant listings found")
    return results


# ── helpers ──────────────────────────────────────────────────────────────────

def _matches_neighborhoods(text: str) -> bool:
    return any(n in text for n in SEARCH_CRITERIA["neighborhoods"])


def _parse_api_items(items: list) -> list[dict]:
    results = []
    for item in items:
        if item.get("type") not in ("ad", None):
            if item.get("type") and item.get("type") not in ("ad",):
                continue

        neighborhood = str(item.get("neighborhood") or "")
        city = str(item.get("city") or "")
        address_obj = item.get("address", {})
        street = ""
        if isinstance(address_obj, dict):
            st = address_obj.get("street", "")
            street = st.get("text", "") if isinstance(st, dict) else str(st)

        combined = f"{neighborhood} {city} {street} {item.get('title', '')}"
        if not _matches_neighborhoods(combined):
            continue

        item_id = str(item.get("id", ""))
        results.append({
            "source": "yad2",
            "listing_id": item_id,
            "title": item.get("title", ""),
            "price": _to_int(item.get("price")),
            "rooms": item.get("rooms"),
            "neighborhood": neighborhood or city,
            "address": street,
            "description": "",
            "floor": item.get("floor"),
            "available_from": item.get("enteranceDate") or item.get("availableFrom"),
            "url": f"https://www.yad2.co.il/item/{item_id}",
        })
    return results


async def _parse_dom(page) -> list[dict]:
    """DOM parser — tries multiple selectors for listing links."""
    # Log page title to help diagnose if it's a CAPTCHA / redirect
    try:
        title = await page.title()
        logger.info(f"Yad2 DOM: page title = '{title}'")
    except Exception:
        pass

    # Try selectors in order
    links_selector = None
    for sel in _LINK_SELECTORS:
        try:
            await page.wait_for_selector(sel, timeout=5_000)
            links_selector = sel
            logger.info(f"Yad2 DOM: found links with selector '{sel}'")
            break
        except Exception:
            continue

    if not links_selector:
        # Log a snippet of the page for debugging
        try:
            snippet = await page.evaluate("document.body.innerText.slice(0, 300)")
            logger.warning(f"Yad2 DOM: no listing links found. Page snippet: {snippet!r}")
        except Exception:
            logger.warning("Yad2 DOM: no listing links found")
        return []

    cards = await page.evaluate(f"""
        () => {{
            const links = document.querySelectorAll('{links_selector}');
            const seen = new Set();
            const results = [];
            links.forEach(a => {{
                // Extract ID from href patterns like /item/XXXX or /realestate/item/TYPE/XXXX
                const idMatch = a.href.match(/\\/item\\/(?:[^\\/]+\\/)?([A-Za-z0-9_-]{{4,}})/);
                const id = idMatch ? idMatch[1] : null;
                if (!id || seen.has(id)) return;
                seen.add(id);

                let container = a;
                for (let i = 0; i < 8; i++) {{
                    if (!container.parentElement) break;
                    container = container.parentElement;
                    const cls = container.className || '';
                    if (cls.includes('feedItem') || cls.includes('feed-item') ||
                        cls.includes('listing') || container.tagName === 'ARTICLE') break;
                }}

                results.push({{
                    id: id,
                    text: container.innerText || '',
                    href: a.href.split('?')[0],
                }});
            }});
            return results;
        }}
    """)

    results = []
    for card in cards:
        text = card.get("text", "")
        href = card.get("href", "")
        listing_id = card.get("id", "")

        if not listing_id or not _matches_neighborhoods(text):
            continue

        price_match = re.search(r"₪\s*([\d,]+)", text)
        price = int(price_match.group(1).replace(",", "")) if price_match else 0
        if price and price > SEARCH_CRITERIA["max_price"]:
            continue

        rooms_match = re.search(r"(\d[.,]?\d?)\s*חדר", text)
        rooms = float(rooms_match.group(1).replace(",", ".")) if rooms_match else None

        neighborhood = _extract_neighborhood(text)

        lines = [l.strip() for l in text.split("\n") if l.strip()]
        address = ""
        for line in lines[1:]:
            if re.search(r"₪|חדר|תל אביב|קומה|מ״ר", line):
                continue
            address = line
            break

        results.append({
            "source": "yad2",
            "listing_id": listing_id,
            "title": lines[0] if lines else "",
            "price": price,
            "rooms": rooms,
            "neighborhood": neighborhood,
            "address": address,
            "description": text[:300],
            "floor": None,
            "available_from": None,
            "url": href,
        })

    return results


def _extract_neighborhood(text: str) -> str:
    for n in SEARCH_CRITERIA["neighborhoods"]:
        if n in text:
            return n
    return ""


def _to_int(val) -> int:
    try:
        return int(str(val).replace(",", "").replace(" ", ""))
    except Exception:
        return 0
