"""
Onboarding flow — natural language first, buttons for editing.
"""
from __future__ import annotations

import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from db.storage import get_user, upsert_user

logger = logging.getLogger(__name__)

DESCRIBE, ROOMS, NEIGHBORHOODS = range(3)

ALL_ROOMS = ["1.5", "2", "2.5", "3", "3.5", "4+"]

ALL_NEIGHBORHOODS = [
    "פלורנטין",
    "צפון פלורנטין",
    "לב העיר / מרכז העיר",
    "נווה צדק",
    "כרם התימנים",
    "לוינסקי",
]

NEIGHBORHOOD_CANONICAL = {
    "פלורנטין": ["פלורנטין", "צפון פלורנטין"],
    "צפון פלורנטין": ["צפון פלורנטין", "פלורנטין"],
    "לב העיר / מרכז העיר": ["לב העיר", "מרכז העיר"],
    "נווה צדק": ["נווה צדק"],
    "כרם התימנים": ["כרם התימנים"],
    "לוינסקי": ["לוינסקי"],
}

# Extra aliases not in the display names above
_NEIGHBORHOOD_ALIASES = {
    "לב העיר / מרכז העיר": ["לב תל אביב", "לב-תל אביב", "סנטר", "center"],
    "פלורנטין": ["florentin", "flornetin"],
    "נווה צדק": ["neve tzedek", "neve zedek"],
}

_DEFAULT_NEIGHBORHOODS_CANONICAL = [
    "פלורנטין", "צפון פלורנטין", "לב העיר", "מרכז העיר", "נווה צדק",
]

_ROOM_WORDS = {
    "לזוג": 2.0, "זוג": 2.0,
    "שניים": 2.0, "שתיים": 2.0, "שני חדרים": 2.0, "שתי": 2.0,
    "שלושה": 3.0, "שלוש חדרים": 3.0, "שלושה חדרים": 3.0,
    "ארבעה": 4.0, "ארבע חדרים": 4.0,
    "חדר אחד": 1.0, "חדר וחצי": 1.5,
}


# ── natural-language parser ────────────────────────────────────────────────────

def _parse_natural_language(text: str) -> dict:
    result: dict = {}

    # Max price: "עד 7000" / "מקסימום 7,000" / "7000 ₪" / "7000 שקל"
    for pat in [
        r'עד\s*[₪]?\s*([\d,]+)',
        r'מקסימום\s*([\d,]+)',
        r'מקס[׳\']?\s*([\d,]+)',
        r'([\d,]{4,})\s*(?:₪|שקל|ש[״"׳]ח)',
    ]:
        m = re.search(pat, text)
        if m:
            try:
                price = int(m.group(1).replace(',', ''))
                if 1000 <= price <= 50_000:
                    result['max_price'] = price
                    break
            except ValueError:
                pass

    # Rooms: "2 חדרים" / "2.5 חדר" / word phrases
    m = re.search(r'([\d]+(?:[.,][\d])?)\s*[+-]?\s*חדר', text)
    if m:
        try:
            rooms = float(m.group(1).replace(',', '.'))
            result['rooms'] = [rooms]
        except ValueError:
            pass
    else:
        for phrase, num in _ROOM_WORDS.items():
            if phrase in text:
                result['rooms'] = [num]
                break

    # Neighborhoods
    found: list[str] = []
    for display in ALL_NEIGHBORHOODS:
        canonical_list = NEIGHBORHOOD_CANONICAL.get(display, [display])
        aliases = _NEIGHBORHOOD_ALIASES.get(display, [])
        all_terms = canonical_list + aliases
        if any(term.lower() in text.lower() for term in all_terms):
            if display not in found:
                found.append(display)
    result['neighborhoods'] = found

    return result


def _canonical_from_display(display_list: list[str]) -> list[str]:
    canonical: list[str] = []
    for n in display_list:
        for c in NEIGHBORHOOD_CANONICAL.get(n, [n]):
            if c not in canonical:
                canonical.append(c)
    return canonical


def _rooms_display(rooms: list[float] | None) -> str:
    if not rooms:
        return "כל החדרים"
    return ", ".join(str(int(r)) if r == int(r) else str(r) for r in rooms)


# ── keyboards (used by edit commands) ─────────────────────────────────────────

def _rooms_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(ALL_ROOMS), 3):
        row = []
        for r in ALL_ROOMS[i:i + 3]:
            check = "✅ " if r in selected else ""
            row.append(InlineKeyboardButton(f"{check}{r}", callback_data=f"rooms:{r}"))
        rows.append(row)
    all_check = "✅ " if not selected else ""
    rows.append([InlineKeyboardButton(f"{all_check}כל החדרים", callback_data="rooms:all")])
    rows.append([InlineKeyboardButton("➡️ סיים בחירה", callback_data="rooms:done")])
    return InlineKeyboardMarkup(rows)


def _neighborhoods_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for n in ALL_NEIGHBORHOODS:
        check = "✅ " if n in selected else ""
        rows.append([InlineKeyboardButton(f"{check}{n}", callback_data=f"nbhd:{n}")])
    rows.append([InlineKeyboardButton("➡️ סיים בחירה", callback_data="nbhd:done")])
    return InlineKeyboardMarkup(rows)


# ── /start — natural language onboarding ─────────────────────────────────────

async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    user = await get_user(chat_id)

    if user:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⚙️ שנה הגדרות", callback_data="sett:open")
        ]])
        rooms_str = _rooms_display(user["rooms"])
        min_p = user.get("min_price", 0)
        max_p = user.get("max_price", 7_200)
        price_str = f"{min_p:,} – {max_p:,}" if min_p else f"עד {max_p:,}"
        nbhds = ", ".join(user["neighborhoods"])
        await update.message.reply_text(
            f"👋 ברוך השב!\n\n"
            f"🛏 חדרים: {rooms_str}\n"
            f"💰 מחיר: {price_str} ₪\n"
            f"📍 אזורים: {nbhds}\n\n"
            f"הבוט פעיל ומחפש עבורך 🔍",
            reply_markup=keyboard,
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 היי! אני בוט שסורק דירות להשכרה בתל אביב 24/7 ⚡️\n"
        "ברגע שתיפול דירה חדשה שמתאימה לך — אתה הראשון לדעת 🔔\n\n"
        "ספר לי מה אתה מחפש:\n\n"
        "_לדוגמה: 'דירת 2 חדרים עד 7000 ₪ בפלורנטין או נווה צדק'_",
        parse_mode="Markdown",
    )
    return DESCRIBE


async def cmd_reset(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔄 נתחיל מחדש.\n\n"
        "ספר לי מה אתה מחפש:\n\n"
        "_לדוגמה: 'דירת 2 חדרים עד 7000 ₪ בפלורנטין'_",
        parse_mode="Markdown",
    )
    return DESCRIBE


async def msg_describe(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    parsed = _parse_natural_language(text)

    max_price = parsed.get('max_price', 7200)
    rooms_floats: list[float] | None = parsed.get('rooms')
    neighborhoods_display = parsed.get('neighborhoods') or []

    if not neighborhoods_display:
        # No neighborhood detected — use defaults but tell the user
        canonical = _DEFAULT_NEIGHBORHOODS_CANONICAL
        neighborhoods_display = ["פלורנטין", "לב העיר / מרכז העיר", "נווה צדק"]
    else:
        canonical = _canonical_from_display(neighborhoods_display)

    await upsert_user(
        update.effective_chat.id,
        rooms=rooms_floats,
        min_price=0,
        max_price=max_price,
        neighborhoods=canonical,
        active=1,
    )

    rooms_str = _rooms_display(rooms_floats)
    nbhds_str = ", ".join(neighborhoods_display)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚙️ שנה הגדרות", callback_data="sett:open")
    ]])
    await update.message.reply_text(
        f"✅ *הבוט מוגדר ויוצא לסרוק!* 🚀\n\n"
        f"🛏 חדרים: {rooms_str}\n"
        f"💰 מחיר: עד {max_price:,} ₪\n"
        f"📍 אזורים: {nbhds_str}\n\n"
        f"ברגע שתיפול דירה מתאימה — תקבל התראה ⚡️",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return ConversationHandler.END


# ── /setrooms ─────────────────────────────────────────────────────────────────

async def cmd_setrooms(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user = await get_user(update.effective_chat.id)
    if user is None:
        await update.message.reply_text("אין לך עדיין פרופיל. שלח /start להגדרה.")
        return ConversationHandler.END

    current = []
    if user["rooms"]:
        current = [r for r in ALL_ROOMS if (4.0 if r == "4+" else float(r)) in user["rooms"]]
    ctx.user_data["rooms"] = current
    ctx.user_data["_editing_rooms"] = True

    await update.message.reply_text(
        "*שנה חדרים:*\nלחץ לבחירה, ואז ׳סיים בחירה׳.",
        parse_mode="Markdown",
        reply_markup=_rooms_keyboard(current),
    )
    return ROOMS


async def cmd_setneighborhoods(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user = await get_user(update.effective_chat.id)
    if user is None:
        await update.message.reply_text("אין לך עדיין פרופיל. שלח /start להגדרה.")
        return ConversationHandler.END

    current_canonical = set(user.get("neighborhoods", []))
    selected = [
        n for n in ALL_NEIGHBORHOODS
        if any(c in current_canonical for c in NEIGHBORHOOD_CANONICAL.get(n, [n]))
    ]
    ctx.user_data["neighborhoods"] = selected
    ctx.user_data["_editing_neighborhoods"] = True

    await update.message.reply_text(
        "*שנה אזורים:*\nלחץ על האזורים הרצויים, ואז ׳סיים בחירה׳.",
        parse_mode="Markdown",
        reply_markup=_neighborhoods_keyboard(selected),
    )
    return NEIGHBORHOODS


# ── rooms callback ─────────────────────────────────────────────────────────────

async def cb_rooms(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    selected: list[str] = ctx.user_data.setdefault("rooms", [])

    if value == "all":
        selected.clear()
        await query.edit_message_reply_markup(reply_markup=_rooms_keyboard(selected))
        return ROOMS

    if value == "done":
        rooms_floats = [4.0 if r == "4+" else float(r) for r in selected] if selected else None
        rooms_display = _rooms_display(rooms_floats)
        await upsert_user(query.from_user.id, rooms=rooms_floats)
        await query.edit_message_text(
            f"✅ *חדרים עודכנו:* {rooms_display}",
            parse_mode="Markdown",
        )
        ctx.user_data.clear()
        return ConversationHandler.END

    if value in selected:
        selected.remove(value)
    else:
        selected.append(value)

    await query.edit_message_reply_markup(reply_markup=_rooms_keyboard(selected))
    return ROOMS


# ── neighborhoods callback ────────────────────────────────────────────────────

async def cb_neighborhoods(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    selected: list[str] = ctx.user_data.setdefault("neighborhoods", [])

    if value == "done":
        if not selected:
            await query.answer("בחר לפחות אזור אחד", show_alert=True)
            return NEIGHBORHOODS

        canonical = _canonical_from_display(selected)
        nbhds_display = ", ".join(selected)
        await upsert_user(query.from_user.id, neighborhoods=canonical)
        await query.edit_message_text(
            f"✅ *אזורים עודכנו:* {nbhds_display}",
            parse_mode="Markdown",
        )
        ctx.user_data.clear()
        return ConversationHandler.END

    if value in selected:
        selected.remove(value)
    else:
        selected.append(value)

    await query.edit_message_reply_markup(reply_markup=_neighborhoods_keyboard(selected))
    return NEIGHBORHOODS


async def cancel(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("בוטל. שלח /start להתחלה מחדש.")
    return ConversationHandler.END


# ── build the handler ─────────────────────────────────────────────────────────

def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CommandHandler("reset", cmd_reset),
            CommandHandler("setrooms", cmd_setrooms),
            CommandHandler("setneighborhoods", cmd_setneighborhoods),
        ],
        states={
            DESCRIBE: [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_describe)],
            ROOMS: [CallbackQueryHandler(cb_rooms, pattern=r"^rooms:")],
            NEIGHBORHOODS: [CallbackQueryHandler(cb_neighborhoods, pattern=r"^nbhd:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=False,
    )
