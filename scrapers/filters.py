"""
Shared filtering logic applied to all listings before notification.
"""
from __future__ import annotations

from config import SEARCH_CRITERIA

# אם אחד מהביטויים האלה מופיע — זה בעל דירה ישיר, לא מתווך
NOT_BROKER_PHRASES = [
    "ללא תיווך",
    "לא מתיווך",
    "בלי תיווך",
    "ישיר מבעל",
    "מבעל הבית",
    "בעל הדירה",
    "ישירות מהבעלים",
    "ישירות מבעל",
    "owner",
]

# מילות מפתח המציינות מתווך/סוכנות נדל"ן
BROKER_KEYWORDS = [
    # מילות שורש
    "תיווך",
    "תווך",
    "מתווך",
    "מתווכת",
    "מתווכים",
    "מתווכות",
    "לתיווך",
    "דמי תיווך",
    "עמלת תיווך",
    # סוכנויות
    "סוכנות",
    "סוכן נדל",
    "משרד נדל",
    "משרד תיווך",
    # מונחים כלליים — רק ספציפיים, לא מילים גנריות שעלולות להופיע בהקשרים אחרים
    "נדל״ן",
    "נדלן",
    # חברות נדל"ן ישראליות נפוצות
    "אנגלו סכסון",
    "anglo saxon",
    "רימקס",
    "remax",
    "re/max",
    "קושט",
    "אלדר",
    "גוטמן",
    "מדלן",
    "הומס",
    "ישרס",
    "בלו נייטס",
    "נתנאל גרופ",
    "אפי גרופ",
    "פרופימד",
    "רסקו",
    "מגה נדל",
]


def passes_filters(listing: dict, criteria: dict | None = None) -> bool:
    """Returns True if the listing should be sent to Telegram.

    criteria can be a per-user dict; falls back to global SEARCH_CRITERIA.
    """
    c = criteria if criteria is not None else SEARCH_CRITERIA

    price = listing.get("price") or 0

    if c.get("require_price", SEARCH_CRITERIA.get("require_price")):
        if price <= 0:
            return False

    min_price = c.get("min_price", 0)
    if min_price and price and price < min_price:
        return False

    max_price = c.get("max_price", 0)
    if max_price and price and price > max_price:
        return False

    # Only filter by rooms if the listing has a room count and the user specified rooms
    listing_rooms = listing.get("rooms")
    criteria_rooms = c.get("rooms")  # list[float] or None
    if listing_rooms and criteria_rooms:
        if not any(abs(float(listing_rooms) - r) < 0.3 for r in criteria_rooms):
            return False

    if c.get("no_broker", SEARCH_CRITERIA.get("no_broker")):
        if _is_broker_listing(listing):
            return False

    return True


def _is_broker_listing(listing: dict) -> bool:
    text = " ".join([
        str(listing.get("title", "")),
        str(listing.get("description", "")),
        str(listing.get("neighborhood", "")),
    ]).lower()

    # אם מפורש שזה ישיר מבעל — לא מתווך
    if any(phrase.lower() in text for phrase in NOT_BROKER_PHRASES):
        return False

    return any(kw.lower() in text for kw in BROKER_KEYWORDS)
