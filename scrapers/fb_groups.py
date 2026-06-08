from __future__ import annotations

"""
Facebook Groups scraper — lightweight HTTP approach via mbasic.facebook.com.
No browser required. Uses session cookies to fetch the simple HTML version of Facebook.
"""
import asyncio
import logging
import re
from typing import Optional

from config import FACEBOOK_GROUPS, SEARCH_CRITERIA
from scrapers.fb_session import get_cookies, make_client

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


async def fetch_listings(_ctx=None) -> list[dict]:
    cookies = get_cookies()
    if not cookies:
        logger.warning("No Facebook cookies — skipping groups scan")
        return []

    all_results = []
    async with make_client(cookies) as client:
        for group_url in FACEBOOK_GROUPS:
            try:
                listings = await asyncio.wait_for(
                    _scrape_group(client, group_url), timeout=30
                )
                all_results.extend(listings)
            except asyncio.TimeoutError:
                logger.warning(f"Group {group_url}: timed out, skipping")
            except Exception as e:
                logger.error(f"Error scraping group {group_url}: {e}")

    logger.info(f"Facebook Groups: {len(all_results)} total relevant listings found")
    return all_results


async def _scrape_group(client, group_url: str) -> list[dict]:
    m = re.search(r"/groups/(\w+)", group_url)
    if not m:
        return []
    group_id = m.group(1)

    mbasic_url = f"https://mbasic.facebook.com/groups/{group_id}"
    resp = await client.get(mbasic_url)

    if resp.status_code != 200:
        logger.warning(f"Group {group_id}: HTTP {resp.status_code}")
        return []

    if "login" in str(resp.url).lower() or 'id="login_form"' in resp.text:
        logger.warning(f"Group {group_id}: redirected to login — cookies expired")
        return []

    posts = _parse_mbasic_posts(resp.text, group_id)
    logger.info(f"Group {group_url}: {len(posts)} relevant posts")
    return posts


def _parse_mbasic_posts(html: str, group_id: str) -> list[dict]:
    from html.parser import HTMLParser

    class _TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.texts: list[str] = []
            self._current: list[str] = []
            self._depth = 0

        def handle_starttag(self, tag, attrs):
            self._depth += 1

        def handle_endtag(self, tag):
            self._depth -= 1

        def handle_data(self, data):
            data = data.strip()
            if data:
                self._current.append(data)

    results = []

    # Find post blocks — mbasic wraps each post in <div> with a story permalink
    post_pattern = re.compile(
        r'href="(/groups/[^"]*permalink/(\d+)[^"]*)"[^>]*>.*?'
        r'(<div[^>]*>.*?</div>)',
        re.DOTALL
    )

    # Simpler: extract all text blocks between story divs
    # mbasic posts have a "story" anchor linking to /groups/ID/permalink/POST_ID
    permalink_re = re.compile(r'/groups/\w+/permalink/(\d+)')
    post_ids = permalink_re.findall(html)
    seen_ids = set()

    # Split HTML around each story section
    story_re = re.compile(r'<article[^>]*>(.*?)</article>', re.DOTALL)
    articles = story_re.findall(html)

    if not articles:
        # Fallback: split around permalink anchors
        chunks = re.split(r'(?=href="/groups/\w+/permalink/)', html)
        for chunk in chunks:
            m = permalink_re.search(chunk)
            if not m:
                continue
            post_id = m.group(1)
            if post_id in seen_ids:
                continue
            seen_ids.add(post_id)
            text = re.sub(r'<[^>]+>', ' ', chunk)
            text = re.sub(r'\s+', ' ', text).strip()
            result = _try_post(text, post_id, group_id)
            if result:
                results.append(result)
    else:
        for article in articles:
            m = permalink_re.search(article)
            post_id = m.group(1) if m else None
            if not post_id or post_id in seen_ids:
                continue
            seen_ids.add(post_id)
            text = re.sub(r'<[^>]+>', ' ', article)
            text = re.sub(r'\s+', ' ', text).strip()
            result = _try_post(text, post_id, group_id)
            if result:
                results.append(result)

    return results


def _try_post(text: str, post_id: str, group_id: str) -> Optional[dict]:
    if not _is_listing(text):
        return None
    if _has_other_neighborhood(text):
        return None

    price = _extract_price(text)
    if price and price > SEARCH_CRITERIA["max_price"]:
        return None

    neighborhood = _extract_neighborhood(text)

    return {
        "source": "facebook_groups",
        "listing_id": post_id,
        "title": _extract_title(text),
        "price": price,
        "rooms": _extract_rooms(text),
        "neighborhood": neighborhood,
        "address": "",
        "description": text[:400],
        "published_at": None,
        "url": f"https://www.facebook.com/groups/{group_id}/permalink/{post_id}/",
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
