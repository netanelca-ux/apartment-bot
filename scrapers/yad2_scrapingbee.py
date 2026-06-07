"""
Yad2 scraper using ScrapingBee API.
Bypasses Yad2's WAF (Imperva) which blocks Railway datacenter IPs.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from config import SEARCH_CRITERIA

logger = logging.getLogger(__name__)

SCRAPINGBEE_API = "https://app.scrapingbee.com/api/v1/"

SEARCH_URL = (
    "https://www.yad2.co.il/realestate/rent"
    "?topArea=2&city=5000"
    f"&price=0-{SEARCH_CRITERIA['max_price']}"
    "&priceType=monthly"
)


async def fetch_listings(api_key: str) -> list[dict]:
    if not api_key:
        logger.warning("SCRAPINGBEE_API_KEY not set — Yad2 scraper disabled")
        return []

    html = await _get_rendered_html(api_key)
    if not html:
        return []

    # Extract from dehydratedState (React Query cache in Next.js)
    items = _extract_dehydrated_items(html)
    if items:
        results = _parse_dehydrated_items(items)
        logger.info(f"Yad2: {len(results)} listings from dehydratedState")
        return results

    # Fall back to legacy __NEXT_DATA__ or HTML link parsing
    legacy_items = _extract_next_data_items(html)
    if legacy_items:
        results = _parse_api_items(legacy_items)
        logger.info(f"Yad2: {len(results)} listings from __NEXT_DATA__")
        return results

    results = _parse_html_links(html)
    logger.info(f"Yad2: {len(results)} listings from HTML parsing")
    return results


async def _get_rendered_html(api_key: str) -> str:
    try:
        params = {
            "api_key": api_key,
            "url": SEARCH_URL,
            "render_js": "true",
            "wait": 5000,
            "stealth_proxy": "true",
        }
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.get(SCRAPINGBEE_API, params=params)

        if resp.status_code != 200:
            logger.error(f"ScrapingBee error {resp.status_code}: {resp.text[:300]}")
            return ""

        # Check if we got a real Yad2 page or a security block
        if "אתר אבטחה" in resp.text or "Incident ID" in resp.text:
            logger.error("Yad2: ScrapingBee got security block page — check proxy settings")
            return ""

        return resp.text
    except Exception as e:
        logger.error(f"ScrapingBee request failed: {e}")
        return ""


def _extract_dehydrated_items(html: str) -> list:
    """Extract listings from React Query dehydratedState (current Yad2 format)."""
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    for s in scripts:
        if 'dehydratedState' not in s or 'price' not in s:
            continue
        try:
            data = json.loads(s)
            queries = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("dehydratedState", {})
                    .get("queries", [])
            )
            for q in queries:
                qdata = q.get("state", {}).get("data", {})
                if isinstance(qdata, dict) and ("private" in qdata or "agency" in qdata):
                    items: list = []
                    # Tag each item with its section so broker detection is exact
                    for item in (qdata.get("private") or []):
                        items.append({**item, "_ad_section": "private"})
                    for item in (qdata.get("agency") or []):
                        items.append({**item, "_ad_section": "agency"})
                    if items:
                        return items
        except Exception as e:
            logger.debug(f"dehydratedState parse error: {e}")
    return []


def _parse_dehydrated_items(items: list) -> list[dict]:
    """Parse the new Yad2 dehydratedState listing format."""
    results = []
    for item in items:
        addr = item.get("address", {})
        neighborhood = addr.get("neighborhood", {}).get("text", "")
        city = addr.get("city", {}).get("text", "")
        street = addr.get("street", {}).get("text", "")
        house_num = addr.get("house", {}).get("number", "")
        floor = addr.get("house", {}).get("floor")

        combined = f"{neighborhood} {city} {street}"
        if not _matches_neighborhoods(combined):
            continue

        token = item.get("token", "")
        if not token:
            continue

        details = item.get("additionalDetails", {})
        address_str = f"{street} {house_num}".strip() if street else ""
        prop_type = details.get("property", {}).get("text", "דירה")

        # Extract publication date from cover image URL: _20260607140515.jpeg
        meta = item.get("metaData", {})
        cover = meta.get("coverImage", "") if isinstance(meta, dict) else ""
        pub_m = re.search(r'_(\d{4})(\d{2})(\d{2})\d{6}\.', cover)
        published_at = f"{pub_m.group(3)}/{pub_m.group(2)}/{pub_m.group(1)[2:]}" if pub_m else None

        results.append({
            "source": "yad2",
            "listing_id": token,
            "title": f"{prop_type} {address_str}".strip(),
            "price": _to_int(item.get("price")),
            "rooms": details.get("roomsCount"),
            "neighborhood": neighborhood or city,
            "address": address_str,
            "description": "",
            "floor": str(floor) if floor is not None else None,
            "available_from": None,
            "published_at": published_at,
            "ad_type": item.get("adType") or item.get("_ad_section", ""),
            "url": f"https://www.yad2.co.il/realestate/item/tel-aviv-area/{token}",
        })
    return results


def _extract_next_data_items(html: str) -> list:
    """Extract pre-loaded listing data from Next.js __NEXT_DATA__ script tag."""
    m = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html, re.DOTALL
    )
    if not m:
        return []

    try:
        data = json.loads(m.group(1))
        page_props = data.get("props", {}).get("pageProps", {})

        for path in [
            ["feed", "feed_items"],
            ["data", "feed", "feed_items"],
            ["listings"],
            ["data", "listings"],
        ]:
            node = page_props
            for key in path:
                node = node.get(key) if isinstance(node, dict) else None
                if node is None:
                    break
            if isinstance(node, list) and node:
                return node
    except Exception as e:
        logger.debug(f"__NEXT_DATA__ parse failed: {e}")

    return []


def _parse_api_items(items: list) -> list[dict]:
    """Parse structured Yad2 API items (same format as Playwright scraper)."""
    results = []
    for item in items:
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


def _parse_html_links(html: str) -> list[dict]:
    """Extract listings from rendered Yad2 HTML by scanning listing card links."""
    results = []
    seen: set[str] = set()

    # Yad2 uses relative paths: /realestate/item/tel-aviv-area/ITEM_ID
    for m in re.finditer(r'href="(/realestate/item/[^"?]+)', html):
        path = m.group(1)
        # Listing ID is the last path segment
        listing_id = path.rstrip("/").split("/")[-1]
        if not listing_id or listing_id in seen:
            continue
        seen.add(listing_id)

        # Extract text from the surrounding card (~600 chars around the link)
        pos = m.start()
        raw_html = html[max(0, pos - 400):pos + 400]
        text = " ".join(re.sub(r'<[^>]+>', ' ', raw_html).split())

        if not _matches_neighborhoods(text):
            continue

        price_m = (
            re.search(r'([\d,]+)\s*(?:₪|ש[״"׳]?ח)', text)
            or re.search(r'(?:₪|ש[״"׳]?ח)\s*([\d,]+)', text)
        )
        price = 0
        if price_m:
            try:
                price = int((price_m.group(1) or "").replace(",", ""))
                if not 1000 <= price <= 30000:
                    price = 0
            except ValueError:
                pass

        rooms_m = re.search(r'(\d[.,]?\d?)\s*חדר', text)
        rooms = None
        if rooms_m:
            try:
                rooms = float(rooms_m.group(1).replace(",", "."))
            except ValueError:
                pass

        results.append({
            "source": "yad2",
            "listing_id": listing_id,
            "title": text[:100],
            "price": price,
            "rooms": rooms,
            "neighborhood": _extract_neighborhood(text),
            "address": "",
            "description": text[:350],
            "floor": None,
            "available_from": None,
            "url": f"https://www.yad2.co.il{path}",
        })

    return results


def _matches_neighborhoods(text: str) -> bool:
    return any(n in text for n in SEARCH_CRITERIA["neighborhoods"])


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
