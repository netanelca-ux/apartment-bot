from __future__ import annotations

import logging
import re
from typing import Optional

from config import FACEBOOK_GROUPS, SEARCH_CRITERIA
from scrapers.fb_session import get_cookies

logger = logging.getLogger(__name__)

LISTING_KEYWORDS = [
    "להשכרה", "לשכירות", "מוציא לשכירות", "מוציאה לשכירות",
    "מציע לשכירות", "מציעה לשכירות", "דירה פנויה", "דירה להשכרה",
    "מתפנה", "מתפנית", "פנויה", "פנוי", "כניסה מיידית",
    "זמינה", "זמין", "לא מתיווך", "ללא תיווך", "ישיר מבעל", "מבעל הבית",
]
SEARCH_KEYWORDS = ["מחפש", "מחפשת", "מישהו יודע", "האם מישהו", "מחפשים שותף"]

OTHER_NEIGHBORHOODS = [
    "רמת אביב", "הצפון הישן", "הצפון החדש", "רמת החייל", "שכונת התקווה",
    "יד אליהו", "כפר שלם", "שפירא", "קריית שלום", "עזרא", "הארגזים",
    "רמת גן", "גבעתיים", "בני ברק", "חולון", "בת ים", "ראשון לציון",
    "פתח תקווה", "הרצליה", "רעננה",
]

# JS snippet to extract posts from a Facebook group page
_EXTRACT_JS = """
() => {
    const posts = [];
    document.querySelectorAll('[role="article"]').forEach(el => {
        let postHref = '';
        for (const a of el.querySelectorAll('a[href]')) {
            const h = a.href;
            if (h.includes('/posts/') || h.includes('/permalink/') || h.includes('?id=')) {
                postHref = h;
                break;
            }
        }
        posts.push({text: el.innerText, href: postHref});
    });
    return posts;
}
"""


async def fetch_listings(browser=None) -> list[dict]:
    from scrapers.browser import managed_browser, new_page as _new_page

    cookies = get_cookies()
    if not cookies:
        logger.warning("No Facebook cookies — skipping groups scan")
        return []

    fb_cookies = [
        {"name": k, "value": v, "domain": ".facebook.com", "path": "/"}
        for k, v in cookies.items()
    ]

    async def _run(b):
        page = await _new_page(b, cookies=fb_cookies)
        all_results = []
        try:
            for group_url in FACEBOOK_GROUPS:
                m = re.search(r"/groups/(\w+)", group_url)
                if not m:
                    continue
                group_id = m.group(1)
                try:
                    results = await _scrape_group(page, group_id)
                    all_results.extend(results)
                except Exception as e:
                    logger.error(f"Error scraping group {group_id}: {e}")
        finally:
            await page.context.close()
        logger.info(f"Facebook Groups: {len(all_results)} total relevant listings found")
        return all_results

    if browser is not None:
        return await _run(browser)
    async with managed_browser() as b:
        return await _run(b)


async def _scrape_group(page, group_id: str) -> list[dict]:
    url = f"https://www.facebook.com/groups/{group_id}?sorting_setting=CHRONOLOGICAL"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    except Exception as e:
        logger.warning(f"Group {group_id}: navigation failed: {e}")
        return []

    current_url = page.url
    if "login" in current_url or "checkpoint" in current_url:
        logger.warning(f"Group {group_id}: session issue — redirected to {current_url}")
        return []

    # Wait for posts to render
    try:
        await page.wait_for_selector('[role="article"]', timeout=8_000)
    except Exception:
        pass

    try:
        posts_data: list[dict] = await page.evaluate(_EXTRACT_JS)
    except Exception as e:
        logger.warning(f"Group {group_id}: JS evaluation failed: {e}")
        return []

    results = []
    for post in posts_data:
        text = post.get("text", "")
        href = post.get("href", "")
        post_id = _extract_post_id(href)
        if not post_id:
            continue
        result = _try_post(text, post_id, group_id)
        if result:
            results.append(result)

    logger.info(f"Group {group_id}: {len(results)} relevant posts out of {len(posts_data)}")
    return results


def _extract_post_id(href: str) -> str:
    for pattern in [r"/posts/(\d+)", r"permalink/(\d+)", r"[?&]id=(\d+)"]:
        m = re.search(pattern, href)
        if m:
            return m.group(1)
    return ""


def _try_post(text: str, post_id: str, group_id: str) -> Optional[dict]:
    if not _is_listing(text):
        return None
    if _has_other_neighborhood(text):
        return None

    price = _extract_price(text)
    if price and price > SEARCH_CRITERIA["max_price"]:
        return None

    return {
        "source": "facebook_groups",
        "listing_id": post_id,
        "title": _extract_title(text),
        "price": price,
        "rooms": _extract_rooms(text),
        "neighborhood": _extract_neighborhood(text),
        "address": "",
        "description": text[:400],
        "published_at": None,
        "url": f"https://www.facebook.com/groups/{group_id}/posts/{post_id}/",
    }


def _is_listing(text: str) -> bool:
    if any(kw in text for kw in SEARCH_KEYWORDS):
        return False
    return any(kw in text for kw in LISTING_KEYWORDS)


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
