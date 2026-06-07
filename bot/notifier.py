from __future__ import annotations

import logging
import re
from telegram import Bot
from telegram.constants import ParseMode
from config import TELEGRAM_BOT_TOKEN, OWNER_CHAT_ID

logger = logging.getLogger(__name__)

_bot: Bot | None = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=TELEGRAM_BOT_TOKEN)
    return _bot


SOURCE_NAMES = {
    "yad2": "יד2",
    "facebook_marketplace": "פייסבוק מרקטפלייס",
    "facebook_groups": "קבוצת פייסבוק",
}

SOURCE_EMOJIS = {
    "yad2": "🏠",
    "facebook_marketplace": "📘",
    "facebook_groups": "👥",
}

# Phrases that confirm the listing is broker-free (imported logic from filters.py)
_NO_BROKER_PHRASES = [
    "ללא תיווך", "לא מתיווך", "בלי תיווך",
    "ישיר מבעל", "מבעל הבית", "בעל הדירה",
    "ישירות מהבעלים", "ישירות מבעל", "owner",
]

_FEATURES_MAP = [
    (["מעלית"],                          "🛗 מעלית"),
    (["ממ\"ד", "מרחב מוגן", 'ממ"ד'],   "🛡️ ממ״ד"),
    (["מרפסת"],                          "🌿 מרפסת"),
    (["חניה", "חנייה", "parking"],       "🚗 חניה"),
    (["גינה"],                            "🌳 גינה"),
    (["מחסן"],                            "📦 מחסן"),
]

_FLOOR_WORDS = {
    "ראשונה": "1", "ראשון": "1",
    "שנייה": "2", "שני": "2",
    "שלישית": "3", "שלישי": "3",
    "רביעית": "4", "רביעי": "4",
    "חמישית": "5", "חמישי": "5",
    "קרקע": "קרקע",
    "גג": "גג",
}


def _full_text(listing: dict) -> str:
    return f"{listing.get('title', '')} {listing.get('description', '')}".strip()


def _detect_no_broker(text: str) -> bool:
    t = text.lower()
    return any(p.lower() in t for p in _NO_BROKER_PHRASES)


def _extract_floor(listing: dict) -> str | None:
    # Prefer structured field (from yad2 API)
    if listing.get("floor") is not None:
        f = str(listing["floor"]).strip()
        if f and f != "0":
            return f

    text = _full_text(listing)
    # "קומה 3" / "קומה שלישית" / "קומה: 3"
    m = re.search(r"קומה\s*:?\s*(\d+|" + "|".join(_FLOOR_WORDS.keys()) + ")", text)
    if m:
        raw = m.group(1)
        return _FLOOR_WORDS.get(raw, raw)
    return None


def _extract_available_from(listing: dict) -> str | None:
    # Prefer structured field (from yad2 API)
    if listing.get("available_from"):
        return str(listing["available_from"])

    text = _full_text(listing)
    if "כניסה מיידית" in text:
        return "מיידית"
    m = re.search(
        r"כניסה\s*(?:ל|מ|ב)-?\s*(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)",
        text,
    )
    if m:
        return m.group(1)
    return None


def _extract_features(text: str) -> list[str]:
    t = text.lower()
    result = []
    for keywords, label in _FEATURES_MAP:
        if any(kw.lower() in t for kw in keywords):
            result.append(label)
    return result


async def send_listing(listing: dict, chat_id: int):
    source_name = SOURCE_NAMES.get(listing["source"], listing["source"])
    text = _full_text(listing)

    lines: list[str] = []

    # ── Header ───────────────────────────────────────────────────────────────
    neighborhood = listing.get("neighborhood") or listing.get("city") or ""
    header = f"🏠 *להשכרה"
    if neighborhood:
        header += f" · {neighborhood}"
    header += "*"
    lines.append(header)

    # ── Core fields ───────────────────────────────────────────────────────────
    price = listing.get("price")
    if price:
        lines.append(f"💰 מחיר: {int(price):,} ₪")

    if _detect_no_broker(text):
        lines.append("🤝 ללא תיווך")

    rooms = listing.get("rooms")
    if rooms:
        rooms_display = int(rooms) if rooms == int(rooms) else rooms
        lines.append(f"🛏 חדרים: {rooms_display}")

    floor = _extract_floor(listing)
    if floor:
        lines.append(f"🏢 קומה: {floor}")

    available = _extract_available_from(listing)
    if available:
        lines.append(f"📅 כניסה: {available}")

    published = listing.get("published_at")
    if published:
        lines.append(f"🕐 פורסם: {published}")

    address = listing.get("address", "")
    if address:
        lines.append(f"📍 {address}")

    # ── Features ──────────────────────────────────────────────────────────────
    features = _extract_features(text)
    if features:
        lines.append("")
        lines.append("*מאפיינים נוספים:*")
        lines.append(" | ".join(features))

    # ── Description snippet ───────────────────────────────────────────────────
    desc = (listing.get("description") or "").strip()
    if desc:
        clean = re.sub(r'[*_`\[\]\\]', '', desc)
        first_lines = [l.strip() for l in clean.split("\n") if l.strip()][:4]
        snippet = "\n".join(first_lines)[:280]
        if snippet:
            lines.append("")
            lines.append(snippet)

    # ── Footer ────────────────────────────────────────────────────────────────
    lines.append("")
    lines.append(f"_מקור: {source_name}_")
    if listing.get("url"):
        lines.append(f"🔗 [לצפייה במודעה]({listing['url']})")

    message = "\n".join(lines)

    bot = get_bot()
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
        )
        logger.info(f"Sent listing {listing.get('listing_id')} from {listing['source']} to {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send Telegram message to {chat_id}: {e}")
        raise


async def send_status(text: str, chat_id: int | None = None):
    bot = get_bot()
    target = chat_id or OWNER_CHAT_ID
    try:
        await bot.send_message(chat_id=target, text=text)
    except Exception as e:
        logger.error(f"Failed to send status message: {e}")
