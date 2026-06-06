from __future__ import annotations

import logging
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


async def send_listing(listing: dict, chat_id: int):
    emoji = SOURCE_EMOJIS.get(listing["source"], "🏠")
    source_name = SOURCE_NAMES.get(listing["source"], listing["source"])

    price = listing.get("price")
    price_str = f"{int(price):,} ₪/חודש" if price else "מחיר לא צוין"

    rooms = listing.get("rooms")
    rooms_str = f"{rooms} חדרים" if rooms else ""

    neighborhood = listing.get("neighborhood") or listing.get("city") or ""

    parts = [p for p in [rooms_str, price_str, neighborhood] if p]
    header = f"{emoji} *{' | '.join(parts)}*"

    lines = [header]

    if listing.get("address"):
        lines.append(f"📍 {listing['address']}")

    if listing.get("description"):
        desc = listing["description"].strip()
        if len(desc) > 300:
            desc = desc[:297] + "..."
        for ch in ("*", "_", "`", "[", "]"):
            desc = desc.replace(ch, f"\\{ch}")
        lines.append(f"\n{desc}")

    if listing.get("url"):
        lines.append(f"\n🔗 [לצפייה במודעה]({listing['url']})")

    lines.append(f"_מקור: {source_name}_")

    text = "\n".join(lines)

    bot = get_bot()
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
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
