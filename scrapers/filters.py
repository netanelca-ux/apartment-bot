"""
Shared filtering logic applied to all listings before notification.
"""
from config import SEARCH_CRITERIA

# מילות מפתח המציינות מתווך/סוכנות נדל"ן
BROKER_KEYWORDS = [
    "תיווך",
    "מתווך",
    "מתווכת",
    "סוכנות",
    "נכסים",
    "real estate",
    "realty",
    "נדל״ן",
    "נדלן",
    "properties",
    "brokers",
]


def passes_filters(listing: dict) -> bool:
    """Returns True if the listing should be sent to Telegram."""

    # סנן ללא מחיר
    price = listing.get("price") or 0
    if SEARCH_CRITERIA.get("require_price"):
        if price <= 0:
            return False

    # סנן מחיר נמוך מדי (בדר"כ חדר בשיתוף)
    min_price = SEARCH_CRITERIA.get("min_price", 0)
    if min_price and price and price < min_price:
        return False

    # סנן מתווכים
    if SEARCH_CRITERIA.get("no_broker"):
        if _is_broker_listing(listing):
            return False

    return True


def _is_broker_listing(listing: dict) -> bool:
    # בדוק שם מקור/כותרת/תיאור
    text = " ".join([
        str(listing.get("title", "")),
        str(listing.get("description", "")),
        str(listing.get("neighborhood", "")),
    ]).lower()

    for kw in BROKER_KEYWORDS:
        if kw.lower() in text:
            return True

    return False
