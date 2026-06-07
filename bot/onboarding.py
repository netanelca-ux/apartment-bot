"""
Onboarding flow — guides a new user through setting up their search preferences.
"""
from __future__ import annotations

import logging

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

ROOMS, MAX_PRICE, MIN_PRICE, NEIGHBORHOODS = range(4)

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


def _rooms_display(selected: list[str]) -> str:
    return ", ".join(selected) if selected else "—"


# ── step 1: /start ────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    user = await get_user(chat_id)

    if user:
        if not user["rooms"]:
            rooms_str = "כל החדרים"
        else:
            rooms_str = ", ".join(str(int(r)) if r == int(r) else str(r) for r in user["rooms"])
        nbhds = ", ".join(user["neighborhoods"])
        await update.message.reply_text(
            f"👋 ברוך השב!\n\n"
            f"ההגדרות שלך כרגע:\n"
            f"🛏 חדרים: {rooms_str}\n"
            f"💰 מחיר: {user['min_price']:,}–{user['max_price']:,} ₪\n"
            f"📍 אזורים: {nbhds}\n\n"
            f"לשינוי הגדרות שלח /setprice, /setrooms, /setneighborhoods\n"
            f"לאיפוס מלא שלח /reset"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 שלום! אני בוט שמחפש דירות להשכרה ברגע שהן מתפרסמות.\n\n"
        "בוא נגדיר את מה שאתה מחפש.\n\n"
        "*כמה חדרים?* (אפשר לבחור כמה)",
        parse_mode="Markdown",
        reply_markup=_rooms_keyboard([]),
    )
    ctx.user_data["rooms"] = []
    return ROOMS


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data["rooms"] = []
    await update.message.reply_text(
        "*כמה חדרים אתה מחפש?* (אפשר לבחור כמה)",
        parse_mode="Markdown",
        reply_markup=_rooms_keyboard([]),
    )
    return ROOMS


async def cmd_setrooms(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user = await get_user(update.effective_chat.id)
    if user is None:
        await update.message.reply_text(
            "אין לך עדיין פרופיל. שלח /start כדי להגדיר את הגדרות החיפוש שלך."
        )
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
        await update.message.reply_text(
            "אין לך עדיין פרופיל. שלח /start כדי להגדיר את הגדרות החיפוש שלך."
        )
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


# ── step 2: rooms (multi-select) ──────────────────────────────────────────────

async def cb_rooms(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    selected: list[str] = ctx.user_data.setdefault("rooms", [])

    if value == "all":
        # Clear all specific selections — "כל החדרים"
        selected.clear()
        await query.edit_message_reply_markup(reply_markup=_rooms_keyboard(selected))
        return ROOMS

    if value == "done":
        rooms_floats = [4.0 if r == "4+" else float(r) for r in selected] if selected else None
        rooms_display = _rooms_display(selected) if selected else "כל החדרים"

        editing = ctx.user_data.get("_editing_rooms", False)
        if editing:
            await upsert_user(query.from_user.id, rooms=rooms_floats)
            await query.edit_message_text(
                f"✅ *חדרים עודכנו!*\n\n🛏 {rooms_display}",
                parse_mode="Markdown",
            )
            ctx.user_data.clear()
            return ConversationHandler.END

        ctx.user_data["rooms_floats"] = rooms_floats
        await query.edit_message_text(
            f"✅ {rooms_display}\n\n"
            f"*מה המחיר המקסימלי לחודש? (הקלד מספר בשקלים)*",
            parse_mode="Markdown",
        )
        return MAX_PRICE

    # Toggle specific room count
    if value in selected:
        selected.remove(value)
    else:
        selected.append(value)

    await query.edit_message_reply_markup(reply_markup=_rooms_keyboard(selected))
    return ROOMS


# ── step 3: max price ─────────────────────────────────────────────────────────

async def msg_max_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        price = int(update.message.text.replace(",", "").replace("₪", "").strip())
        if not (1000 <= price <= 100_000):
            raise ValueError
    except ValueError:
        await update.message.reply_text("אנא הקלד מספר תקין, למשל: 7200")
        return MAX_PRICE
    ctx.user_data["max_price"] = price
    await update.message.reply_text(
        f"✅ עד {price:,} ₪\n\n"
        f"*מה המחיר המינימלי?* (כדי לסנן חדרים בשיתוף)\n"
        f"הקלד מספר, או /skip אם לא רלוונטי.",
        parse_mode="Markdown",
    )
    return MIN_PRICE


# ── step 4: min price ─────────────────────────────────────────────────────────

async def msg_min_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.lower() in ("/skip", "skip", "0", "-"):
        ctx.user_data["min_price"] = 0
    else:
        try:
            price = int(text.replace(",", "").replace("₪", "").strip())
            if not (0 <= price <= 100_000):
                raise ValueError
            ctx.user_data["min_price"] = price
        except ValueError:
            await update.message.reply_text("אנא הקלד מספר תקין, או /skip לדילוג.")
            return MIN_PRICE

    ctx.user_data.setdefault("neighborhoods", [])
    await update.message.reply_text(
        "*באיזה אזורים תחפש?*\nלחץ על האזורים הרצויים, ואז ׳סיים בחירה׳.",
        parse_mode="Markdown",
        reply_markup=_neighborhoods_keyboard([]),
    )
    return NEIGHBORHOODS


# ── step 5: neighborhoods ─────────────────────────────────────────────────────

async def cb_neighborhoods(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    selected: list[str] = ctx.user_data.setdefault("neighborhoods", [])

    if value == "done":
        if not selected:
            await query.answer("בחר לפחות אזור אחד", show_alert=True)
            return NEIGHBORHOODS

        canonical: list[str] = []
        for n in selected:
            for c in NEIGHBORHOOD_CANONICAL.get(n, [n]):
                if c not in canonical:
                    canonical.append(c)

        editing = ctx.user_data.get("_editing_neighborhoods", False)
        nbhds_display = ", ".join(selected)

        if editing:
            await upsert_user(query.from_user.id, neighborhoods=canonical)
            await query.edit_message_text(
                f"✅ *אזורים עודכנו!*\n\n📍 {nbhds_display}",
                parse_mode="Markdown",
            )
        else:
            rooms_floats = ctx.user_data.get("rooms_floats")
            rooms_raw: list[str] = ctx.user_data.get("rooms", [])
            rooms_display = _rooms_display(rooms_raw) if rooms_raw else "כל החדרים"
            min_p = ctx.user_data.get("min_price", 0)
            max_p = ctx.user_data["max_price"]
            price_display = f"{min_p:,}–{max_p:,}" if min_p else f"עד {max_p:,}"

            await upsert_user(
                query.from_user.id,
                rooms=rooms_floats,
                min_price=min_p,
                max_price=max_p,
                neighborhoods=canonical,
                active=1,
            )
            await query.edit_message_text(
                f"✅ *הבוט מוגדר!*\n\n"
                f"🛏 חדרים: {rooms_display}\n"
                f"💰 מחיר: {price_display} ₪\n"
                f"📍 אזורים: {nbhds_display}\n\n"
                f"תתחיל לקבל התראות ברגע שיופיעו דירות מתאימות 🏠\n\n"
                f"_שלח /help לרשימת פקודות_",
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
            ROOMS: [CallbackQueryHandler(cb_rooms, pattern=r"^rooms:")],
            MAX_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_max_price)],
            MIN_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_min_price),
                CommandHandler("skip", msg_min_price),
            ],
            NEIGHBORHOODS: [CallbackQueryHandler(cb_neighborhoods, pattern=r"^nbhd:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=False,
    )
