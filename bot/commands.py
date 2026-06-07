from __future__ import annotations

"""
Telegram command handlers.
- Per-user commands (/status, /setprice, /setminprice, /setrooms): any registered user.
- Admin commands (/scan, /pause, /resume): OWNER_CHAT_ID only.
"""
import logging
from typing import Callable, Coroutine, Any

from telegram import Update
from telegram.ext import ContextTypes

import config
from db.storage import get_user, upsert_user

logger = logging.getLogger(__name__)

_paused = False
_scan_all_callback: Callable[[], Coroutine[Any, Any, None]] | None = None


def set_scan_callback(cb: Callable[[], Coroutine[Any, Any, None]]) -> None:
    global _scan_all_callback
    _scan_all_callback = cb


def is_paused() -> bool:
    return _paused


def _is_owner(update: Update) -> bool:
    return str(update.effective_chat.id) == str(config.OWNER_CHAT_ID)


async def _require_user(update: Update) -> dict | None:
    """Return the user's DB record, or send an onboarding nudge and return None."""
    user = await get_user(update.effective_chat.id)
    if user is None:
        await update.message.reply_text(
            "אין לך עדיין פרופיל. שלח /start כדי להגדיר את הגדרות החיפוש שלך."
        )
    return user


async def cmd_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "🤖 *פקודות הבוט:*\n\n"
        "/start — הגדר חיפוש חדש\n"
        "/status — הגדרות נוכחיות שלך\n"
        "/setprice 7500 — שנה מחיר מקסימלי\n"
        "/setminprice 4500 — שנה מחיר מינימלי\n"
        "/setrooms 2 — שנה מספר חדרים \\(2, 2\\.5, 3…\\)\n"
        "/setneighborhoods — שנה אזורים\n"
        "/pause — השהה קבלת התראות\n"
        "/resume — חדש קבלת התראות\n"
        "/reset — הגדר חיפוש מחדש\n"
        "/help — הצג עזרה זו"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _require_user(update)
    if user is None:
        return
    status_icon = "⏸" if not user["active"] else "✅"
    status_label = "מושהה" if not user["active"] else "פעיל"
    if not user["rooms"]:
        rooms_str = "כל החדרים"
    else:
        rooms_str = ", ".join(str(int(r)) if r == int(r) else str(r) for r in user["rooms"])
    neighborhoods = ", ".join(user["neighborhoods"])
    text = (
        f"*סטטוס: {status_icon} {status_label}*\n\n"
        f"🛏 חדרים: `{rooms_str}`\n"
        f"💰 טווח מחיר: `{user['min_price']:,} – {user['max_price']:,} ₪`\n"
        f"📍 שכונות: {neighborhoods}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_scan(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    if _paused:
        await update.message.reply_text("⏸ הבוט מושהה כלל-מערכתית. שלח /resume כדי להמשיך.")
        return
    await update.message.reply_text("🔍 מתחיל סריקה בכל המקורות...")
    if _scan_all_callback:
        await _scan_all_callback()
        await update.message.reply_text("✅ סריקה הסתיימה.")


async def cmd_setprice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _require_user(update)
    if user is None:
        return
    try:
        price = int(ctx.args[0])
        if not (500 <= price <= 100_000):
            raise ValueError("out of range")
        await upsert_user(update.effective_chat.id, max_price=price)
        await update.message.reply_text(f"✅ מחיר מקסימלי עודכן ל-*{price:,} ₪*", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("שימוש: `/setprice 7500`", parse_mode="Markdown")


async def cmd_setminprice(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _require_user(update)
    if user is None:
        return
    try:
        price = int(ctx.args[0])
        if not (0 <= price <= 100_000):
            raise ValueError("out of range")
        await upsert_user(update.effective_chat.id, min_price=price)
        await update.message.reply_text(f"✅ מחיר מינימלי עודכן ל-*{price:,} ₪*", parse_mode="Markdown")
    except (IndexError, ValueError):
        await update.message.reply_text("שימוש: `/setminprice 4500`", parse_mode="Markdown")



async def cmd_pause(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _require_user(update)
    if user is None:
        return
    await upsert_user(update.effective_chat.id, active=0)
    await update.message.reply_text("⏸ לא תקבל יותר התראות. שלח /resume כדי להמשיך.")


async def cmd_resume(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _require_user(update)
    if user is None:
        return
    await upsert_user(update.effective_chat.id, active=1)
    await update.message.reply_text("▶️ חזרת לקבל התראות!")
