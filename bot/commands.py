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
        "/settings — פאנל הגדרות \\(חדרים, מחיר, אזורים, תיווך\\)\n"
        "/scan — סרוק עכשיו \\(בעל בלבד\\)\n"
        "/reset — הגדר חיפוש מחדש\n"
        "/help — הצג עזרה זו"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")




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
