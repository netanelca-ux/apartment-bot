"""
Shared filtering logic applied to all listings before notification.
"""
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
    # מונחים כלליים
    "real estate",
    "realty",
    "נדל״ן",
    "נדלן",
    "properties",
    "brokers",
    "broker",
    "agent",
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
    text = " ".join([
        str(listing.get("title", "")),
        str(listing.get("description", "")),
        str(listing.get("neighborhood", "")),
    ]).lower()

    # אם מפורש שזה ישיר מבעל — לא מתווך
    if any(phrase.lower() in text for phrase in NOT_BROKER_PHRASES):
        return False

    return any(kw.lower() in text for kw in BROKER_KEYWORDS)
