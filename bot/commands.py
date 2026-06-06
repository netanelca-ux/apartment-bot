from __future__ import annotations

"""
Telegram command handlers — lets the user control the bot via chat.
Only the configured TELEGRAM_CHAT_ID can send commands.
"""
import logging
from typing import Callable, Coroutine, Any

from telegram import Update
from telegram.ext import ContextTypes

import config

logger = logging.getLogger(__name__)

_paused = False
_scan_all_callback: Callable[[], Coroutine[Any, Any, None]] | None = None


def set_scan_callback(cb: Callable[[], Coroutine[Any, Any, None]]) -> None:
    global _scan_all_callback
    _scan_all_callback = cb


def is_paused() -> bool:
    return _paused


def _ok(update: Update) -> bool:
    """Return True only for the authorized chat."""
    return str(update.effective_chat.id) == str(config.TELEGRAM_CHAT_ID)


async def cmd_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ok(update):
        return
    text = (
        "🤖 *פקודות הבוט:*\n\n"
        "/status — הגדרות נוכחיות\n"
        "/scan — סריקה מיידית בכל המקורות\n"
        "/setprice 7500 — שנה מחיר מקסימלי\n"
        "/setminprice 4500 — שנה מחיר מינימלי\n"
        "/setrooms 2 — שנה מספר חדרים \\(2, 2\\.5, 3…\\)\n"
        "/pause — השהה סריקות אוטומטיות\n"
        "/resume — חדש סריקות\n"
        "/help — הצג עזרה זו"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ok(update):
        return
    c = config.SEARCH_CRITERIA
    status_icon = "⏸" if _paused else "✅"
    status_label = "מושהה" if _paused else "פעיל"
    neighborhoods = ", ".join(c["neighborhoods"])
    text = (
        f"*סטטוס: {status_icon} {status_label}*\n\n"
        f"🛏 חדרים: `{c['rooms']}`\n"
        f"💰 טווח מחיר: `{c.get('min_price', 0):,} – {c['max_price']:,} ₪`\n"
        f"📍 שכונות: {neighborhoods}\n"
        f"🏷 רק עם מחיר: {'כן' if c.get('require_price') else 'לא'}\n"
        f"🚫 ללא תיווך: {'כן' if c.get('no_broker') else 'לא'}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_scan(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ok(update):
        return
    if _paused:
        await update.message.reply_text("⏸ הבוט מושהה. שלח /resume כדי להמשיך.")
        return
    await update.message.reply_text("🔍 מתחיל סריקה בכל המקורות...")
    if _scan_all_callback:
        await _scan_all_callback()
        await update.message.reply_text("✅ סריקה הסתיימה.")


async def cmd_setprice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ok(update):
        return
    try:
        price = int(ctx.args[0])
        if not (500 <= price <= 100_000):
            raise ValueError("out of range")
        config.SEARCH_CRITERIA["max_price"] = price
        await update.message.reply_text(f"✅ מחיר מקסימלי עודכן ל-*{price:,} ₪*", parse_mode="Markdown")
        logger.info(f"max_price changed to {price} via Telegram command")
    except (IndexError, ValueError):
        await update.message.reply_text("שימוש: `/setprice 7500`", parse_mode="Markdown")


async def cmd_setminprice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ok(update):
        return
    try:
        price = int(ctx.args[0])
        if not (0 <= price <= 100_000):
            raise ValueError("out of range")
        config.SEARCH_CRITERIA["min_price"] = price
        await update.message.reply_text(f"✅ מחיר מינימלי עודכן ל-*{price:,} ₪*", parse_mode="Markdown")
        logger.info(f"min_price changed to {price} via Telegram command")
    except (IndexError, ValueError):
        await update.message.reply_text("שימוש: `/setminprice 4500`", parse_mode="Markdown")


async def cmd_setrooms(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _ok(update):
        return
    try:
        rooms = float(ctx.args[0].replace(",", "."))
        if rooms <= 0:
            raise ValueError("must be positive")
        config.SEARCH_CRITERIA["rooms"] = rooms
        display = int(rooms) if rooms == int(rooms) else rooms
        await update.message.reply_text(f"✅ מספר חדרים עודכן ל-*{display}*", parse_mode="Markdown")
        logger.info(f"rooms changed to {rooms} via Telegram command")
    except (IndexError, ValueError):
        await update.message.reply_text("שימוש: `/setrooms 2` או `/setrooms 2.5`", parse_mode="Markdown")


async def cmd_pause(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global _paused
    if not _ok(update):
        return
    _paused = True
    await update.message.reply_text("⏸ הסריקות הושהו. שלח /resume כדי להמשיך.")
    logger.info("Bot paused via Telegram command")


async def cmd_resume(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    global _paused
    if not _ok(update):
        return
    _paused = True  # set first to avoid race
    _paused = False
    await update.message.reply_text("▶️ הסריקות חודשו!")
    logger.info("Bot resumed via Telegram command")
