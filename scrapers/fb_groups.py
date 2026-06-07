from __future__ import annotations

"""
Facebook Groups scraper — GraphQL interception approach.
Intercepts Facebook's internal GraphQL API calls to extract post data reliably,
instead of relying on DOM selectors that break frequently.
"""
import asyncio
import base64
import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Optional

from playwright.async_api import BrowserContext, Response

from config import FACEBOOK_GROUPS, SEARCH_CRITERIA

logger = logging.getLogger(__name__)

# Keywords that indicate a FOR-RENT post (not someone searching)
LISTING_KEYWORDS = [
    "להשכרה", "לשכירות", "מוציא לשכירות", "מוציאה לשכירות",
    "מציע לשכירות", "מציעה לשכירות", "דירה פנויה", "דירה להשכרה",
    "מתפנה", "מתפנית", "פנויה", "פנוי", "כניסה מיידית",
    "זמינה", "זמין", "לא מתיווך", "ללא תיווך", "ישיר מבעל", "מבעל הבית",
]

# Keywords that indicate a SEARCH post (exclude these)
SEARCH_KEYWORDS = ["מחפש", "מחפשת", "מישהו יודע", "האם מישהו", "מחפשים שותף"]


async def fetch_listings(context: BrowserContext) -> list[dict]:
    semaphore = asyncio.Semaphore(3)

    async def scrape_with_limit(url: str) -> list[dict]:
        async with semaphore:
            try:
                return await asyncio.wait_for(_scrape_group(context, url), timeout=90)
            except asyncio.TimeoutError:
                logger.warning(f"Group {url}: timed out after 90s, skipping")
                return []
            except Exception as e:
                logger.error(f"Error scraping group {url}: {e}")
                return []

    results_nested = await asyncio.gather(*[scrape_with_limit(url) for url in FACEBOOK_GROUPS])
    all_results = [item for sublist in results_nested for item in sublist]
    logger.info(f"Facebook Groups: {len(all_results)} total relevant listings found")
    return all_results


# ── GraphQL parsing helpers ───────────────────────────────────────────────────

def _decode_fb_id(enc: str) -> Optional[str]:
    """Decode a base64 Facebook ID and return the embedded numeric post ID."""
    try:
        padded = enc + "=" * ((4 - len(enc) % 4) % 4)
        decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
        # Formats: "feedback:1234567890"  or  "S:_I123:VK:1234567890"
        m = re.search(r":(\d{10,})", decoded)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _get_nested(obj: dict, *keys):
    """Safe nested dict access."""
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def _extract_post_text(node: dict) -> str:
    """Try multiple known GraphQL paths to extract the post text."""
    # Path 1: group feed – message inside comet_sections
    t = _get_nested(node, "comet_sections", "content", "story",
                    "comet_sections", "message", "story", "message", "text")
    if t:
        return t

    # Path 2: alternate message_container path
    t = _get_nested(node, "comet_sections", "content", "story",
                    "comet_sections", "message_container", "story", "message", "text")
    if t:
        return t

    # Path 3: simplified (some post types)
    t = _get_nested(node, "comet_sections", "content", "story", "message", "text")
    if t:
        return t

    # Path 4: rich_message array (multi-segment posts)
    parts = _get_nested(node, "comet_sections", "content", "story",
                        "comet_sections", "message", "rich_message")
    if isinstance(parts, list):
        return " ".join(p.get("text", "") for p in parts if isinstance(p, dict))

    return ""


def _format_timestamp(ts: int) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    today = date.today()
    d = dt.date()
    if d == today:
        return f"היום {dt.strftime('%H:%M')}"
    if (today.toordinal() - d.toordinal()) == 1:
        return f"אתמול {dt.strftime('%H:%M')}"
    return dt.strftime('%d/%m/%y')


def _extract_creation_time(node: dict) -> Optional[str]:
    for path in [
        ("comet_sections", "context", "story", "creation_time"),
        ("comet_sections", "context_layout", "story", "creation_time"),
        ("feedback", "creation_time"),
        ("creation_time",),
    ]:
        t = _get_nested(node, *path)
        if isinstance(t, (int, float)) and t > 0:
            return _format_timestamp(int(t))
    return None


def _extract_post_id(node: dict) -> Optional[str]:
    """Extract numeric post ID from a story node."""
    # feedback.id is most reliable (base64-encoded "feedback:NUMERIC_ID")
    feedback_id = _get_nested(node, "feedback", "id")
    if feedback_id:
        dec = _decode_fb_id(feedback_id)
        if dec:
            return dec

    # Fall back to node.id
    node_id = node.get("id")
    if node_id:
        dec = _decode_fb_id(node_id)
        if dec:
            return dec

    return None


def _parse_graphql_response(data: dict) -> list[tuple[str, str, Optional[str]]]:
    """Return [(post_id, text, published_at)] found in one GraphQL response object."""
    results = []

    # Group feed: data.node.group_feed.edges[].node
    edges = _get_nested(data, "data", "node", "group_feed", "edges")
    if isinstance(edges, list):
        for edge in edges:
            node = edge.get("node", {}) if isinstance(edge, dict) else {}
            post_id = _extract_post_id(node)
            text = _extract_post_text(node)
            if post_id and text:
                results.append((post_id, text, _extract_creation_time(node)))

    # Single story page: data.node (when __typename == "Story")
    single = _get_nested(data, "data", "node")
    if isinstance(single, dict) and single.get("__typename") == "Story":
        post_id = _extract_post_id(single)
        text = _extract_post_text(single)
        if post_id and text:
            results.append((post_id, text, _extract_creation_time(single)))

    return results


# ── main scraper ──────────────────────────────────────────────────────────────

async def _scrape_group(context: BrowserContext, group_url: str) -> list[dict]:
    page = await context.new_page()

    m = re.search(r"/groups/(\w+)", group_url)
    group_id = m.group(1) if m else ""

    raw_posts: dict[str, dict] = {}  # post_id → {text, published_at}

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
                    for post_id, text, published_at in _parse_graphql_response(parsed):
                        if post_id not in raw_posts:
                            raw_posts[post_id] = {"text": text, "published_at": published_at}
                except Exception:
                    pass
        except Exception:
            pass

    page.on("response", on_response)
    results = []

    try:
        await page.goto(group_url, wait_until="domcontentloaded", timeout=40_000)

        if await page.query_selector('form[data-testid="royal_login_form"]'):
            logger.warning(f"Facebook login required for {group_url}. Run tools/fb_login.py.")
            return []

        # Scroll to trigger more GraphQL feed requests
        await page.wait_for_timeout(2000)
        for _ in range(5):
            await page.evaluate("window.scrollBy(0, 2000)")
            await page.wait_for_timeout(1500)

        logger.debug(f"Group {group_url}: {len(raw_posts)} posts intercepted via GraphQL")

        for post_id, data in raw_posts.items():
            text = data["text"]
            if not _is_listing(text):
                continue

            price = _extract_price(text)
            if price and price > SEARCH_CRITERIA["max_price"]:
                continue

            rooms = _extract_rooms(text)

            neighborhood = _extract_neighborhood(text)
            if not neighborhood and _has_other_neighborhood(text):
                continue

            post_url = f"https://www.facebook.com/groups/{group_id}/permalink/{post_id}/"
            results.append({
                "source": "facebook_groups",
                "listing_id": post_id,
                "title": _extract_title(text),
                "price": price,
                "rooms": rooms,
                "neighborhood": neighborhood,
                "address": "",
                "description": text[:400],
                "published_at": data.get("published_at"),
                "url": post_url,
            })

    except Exception as e:
        logger.error(f"Error in _scrape_group({group_url}): {e}")
    finally:
        await page.close()

    logger.info(f"Group {group_url}: {len(results)} relevant posts ({len(raw_posts)} total from GraphQL)")
    return results


# ── text helpers ──────────────────────────────────────────────────────────────

def _is_listing(text: str) -> bool:
    if any(kw in text for kw in SEARCH_KEYWORDS):
        return False
    return any(kw in text for kw in LISTING_KEYWORDS)


OTHER_NEIGHBORHOODS = [
    "רמת אביב", "הצפון הישן", "הצפון החדש", "רמת החייל", "שכונת התקווה",
    "יד אליהו", "כפר שלם", "שפירא", "קריית שלום", "עזרא", "הארגזים",
    "רמת גן", "גבעתיים", "בני ברק", "חולון", "בת ים", "ראשון לציון",
    "פתח תקווה", "הרצליה", "רעננה",
]


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


def _extract_rooms(text: str) -> float | None:
    match = re.search(r"(\d[.,]?\d?)\s*חדר", text)
    if match:
        try:
            return float(match.group(1).replace(",", "."))
        except ValueError:
            pass
    return None


def _extract_title(text: str) -> str:
    first_line = text.split("\n")[0].strip()
    return first_line[:100] if first_line else text[:100]
