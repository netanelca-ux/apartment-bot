"""
Unified settings panel — all settings in one interactive message.
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

SP_HOME, SP_ROOMS, SP_NBHD, SP_PRICE_CUSTOM = range(4)

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

PRICE_PRESETS = [6_000, 6_500, 7_000, 7_500, 8_000]


# ── panel builders ─────────────────────────────────────────────────────────────

def _panel_text(user: dict) -> str:
    rooms = user.get("rooms")
    if not rooms:
        rooms_str = "כל החדרים"
    else:
        rooms_str = ", ".join(str(int(r)) if r == int(r) else str(r) for r in rooms)
    min_p = user.get("min_price", 0)
    max_p = user.get("max_price", 7_200)
    price_str = f"{min_p:,} – {max_p:,}" if min_p else f"עד {max_p:,}"
    nbhds = ", ".join(user.get("neighborhoods", []))
    broker = "ללא תיווך" if user.get("broker_filter", "no_broker") == "no_broker" else "כולל מתווכים"
    status_str = "✅ פעיל" if user.get("active", 1) else "⏸ מושהה"
    return (
        f"⚙️ *הגדרות החיפוש*\n\n"
        f"🛏  חדרים:  {rooms_str}\n"
        f"💰  מחיר:    {price_str} ₪\n"
        f"📍  אזורים: {nbhds}\n"
        f"🤝  תיווך:   {broker}\n"
        f"📡  סטטוס:  {status_str}"
    )


def _panel_keyboard(user: dict) -> InlineKeyboardMarkup:
    toggle = "⏸ השהה" if user.get("active", 1) else "▶️ הפעל"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛏 חדרים", callback_data="sp:rooms"),
            InlineKeyboardButton("💰 מחיר", callback_data="sp:price"),
        ],
        [
            InlineKeyboardButton("📍 אזורים", callback_data="sp:nbhd"),
            InlineKeyboardButton("🤝 תיווך", callback_data="sp:broker"),
        ],
        [InlineKeyboardButton(toggle, callback_data="sp:toggle")],
    ])


def _rooms_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(ALL_ROOMS), 3):
        row = []
        for r in ALL_ROOMS[i:i + 3]:
            check = "✅ " if r in selected else ""
            row.append(InlineKeyboardButton(f"{check}{r}", callback_data=f"sp_rooms:{r}"))
        rows.append(row)
    all_check = "✅ " if not selected else ""
    rows.append([InlineKeyboardButton(f"{all_check}כל החדרים", callback_data="sp_rooms:all")])
    rows.append([
        InlineKeyboardButton("⬅️ חזרה", callback_data="sp_rooms:back"),
        InlineKeyboardButton("✅ שמור", callback_data="sp_rooms:done"),
    ])
    return InlineKeyboardMarkup(rows)


def _nbhd_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for n in ALL_NEIGHBORHOODS:
        check = "✅ " if n in selected else ""
        rows.append([InlineKeyboardButton(f"{check}{n}", callback_data=f"sp_nbhd:{n}")])
    rows.append([
        InlineKeyboardButton("⬅️ חזרה", callback_data="sp_nbhd:back"),
        InlineKeyboardButton("✅ שמור", callback_data="sp_nbhd:done"),
    ])
    return InlineKeyboardMarkup(rows)


def _price_keyboard(current_max: int) -> InlineKeyboardMarkup:
    rows: list[list] = []
    row: list = []
    for p in PRICE_PRESETS:
        check = "✅ " if p == current_max else ""
        row.append(InlineKeyboardButton(f"{check}{p:,}", callback_data=f"sp_price:{p}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("✏️ סכום אחר", callback_data="sp_price:custom")])
    rows.append([InlineKeyboardButton("⬅️ חזרה", callback_data="sp_price:back")])
    return InlineKeyboardMarkup(rows)


def _broker_keyboard(current: str) -> InlineKeyboardMarkup:
    no_check = "✅ " if current == "no_broker" else ""
    any_check = "✅ " if current == "any" else ""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{no_check}ללא תיווך בלבד", callback_data="sp_broker:no_broker")],
        [InlineKeyboardButton(f"{any_check}הכל (כולל מתווכים)", callback_data="sp_broker:any")],
        [InlineKeyboardButton("⬅️ חזרה", callback_data="sp_broker:back")],
    ])


async def _refresh_panel(query, chat_id: int) -> None:
    user = await get_user(chat_id)
    await query.edit_message_text(
        _panel_text(user),
        parse_mode="Markdown",
        reply_markup=_panel_keyboard(user),
    )


# ── entry points ───────────────────────────────────────────────────────────────

async def cmd_settings(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user = await get_user(update.effective_chat.id)
    if user is None:
        await update.message.reply_text("אין לך עדיין פרופיל. שלח /start להגדרה.")
        return ConversationHandler.END
    await update.message.reply_text(
        _panel_text(user),
        parse_mode="Markdown",
        reply_markup=_panel_keyboard(user),
    )
    return SP_HOME


async def cb_sp_open(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> int:
    """Opens settings panel from the 'sett:open' button in the onboarding message."""
    query = update.callback_query
    await query.answer()
    await _refresh_panel(query, query.from_user.id)
    return SP_HOME


# ── home actions ───────────────────────────────────────────────────────────────

async def cb_sp_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]
    chat_id = query.from_user.id
    user = await get_user(chat_id)

    if action == "rooms":
        current = []
        if user["rooms"]:
            current = [r for r in ALL_ROOMS if (4.0 if r == "4+" else float(r)) in user["rooms"]]
        ctx.user_data["sp_rooms"] = current
        await query.edit_message_text(
            "🛏 *בחר מספר חדרים:*\nאפשר לבחור כמה",
            parse_mode="Markdown",
            reply_markup=_rooms_keyboard(current),
        )
        return SP_ROOMS

    if action == "nbhd":
        current_canonical = set(user.get("neighborhoods", []))
        selected = [
            n for n in ALL_NEIGHBORHOODS
            if any(c in current_canonical for c in NEIGHBORHOOD_CANONICAL.get(n, [n]))
        ]
        ctx.user_data["sp_nbhd"] = selected
        await query.edit_message_text(
            "📍 *בחר אזורים:*",
            parse_mode="Markdown",
            reply_markup=_nbhd_keyboard(selected),
        )
        return SP_NBHD

    if action == "price":
        current_max = user.get("max_price", 7_200)
        await query.edit_message_text(
            "💰 *בחר מחיר מקסימלי לחודש:*",
            parse_mode="Markdown",
            reply_markup=_price_keyboard(current_max),
        )
        return SP_HOME

    if action == "broker":
        current = user.get("broker_filter", "no_broker")
        await query.edit_message_text(
            "🤝 *סינון תיווך:*",
            parse_mode="Markdown",
            reply_markup=_broker_keyboard(current),
        )
        return SP_HOME

    if action == "toggle":
        await upsert_user(chat_id, active=0 if user.get("active", 1) else 1)
        await _refresh_panel(query, chat_id)

    return SP_HOME


# ── rooms sub-menu ─────────────────────────────────────────────────────────────

async def cb_sp_rooms(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    selected: list[str] = ctx.user_data.setdefault("sp_rooms", [])

    if value == "back":
        await _refresh_panel(query, query.from_user.id)
        return SP_HOME

    if value == "done":
        rooms_floats = [4.0 if r == "4+" else float(r) for r in selected] if selected else None
        await upsert_user(query.from_user.id, rooms=rooms_floats)
        await _refresh_panel(query, query.from_user.id)
        return SP_HOME

    if value == "all":
        selected.clear()
    elif value in selected:
        selected.remove(value)
    else:
        selected.append(value)

    await query.edit_message_reply_markup(reply_markup=_rooms_keyboard(selected))
    return SP_ROOMS


# ── neighborhoods sub-menu ────────────────────────────────────────────────────

async def cb_sp_nbhd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    selected: list[str] = ctx.user_data.setdefault("sp_nbhd", [])

    if value == "back":
        await _refresh_panel(query, query.from_user.id)
        return SP_HOME

    if value == "done":
        if not selected:
            await query.answer("בחר לפחות אזור אחד", show_alert=True)
            return SP_NBHD
        canonical: list[str] = []
        for n in selected:
            for c in NEIGHBORHOOD_CANONICAL.get(n, [n]):
                if c not in canonical:
                    canonical.append(c)
        await upsert_user(query.from_user.id, neighborhoods=canonical)
        await _refresh_panel(query, query.from_user.id)
        return SP_HOME

    if value in selected:
        selected.remove(value)
    else:
        selected.append(value)

    await query.edit_message_reply_markup(reply_markup=_nbhd_keyboard(selected))
    return SP_NBHD


# ── price sub-menu ─────────────────────────────────────────────────────────────

async def cb_sp_price(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    chat_id = query.from_user.id

    if value == "back":
        await _refresh_panel(query, chat_id)
        return SP_HOME

    if value == "custom":
        await query.edit_message_text(
            "💰 *הקלד מחיר מקסימלי לחודש:*\n\n_לדוגמה: 7800_",
            parse_mode="Markdown",
        )
        return SP_PRICE_CUSTOM

    try:
        await upsert_user(chat_id, max_price=int(value))
        await _refresh_panel(query, chat_id)
    except ValueError:
        pass
    return SP_HOME


async def msg_sp_custom_price(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        price = int(text.replace(",", "").replace("₪", "").strip())
        if not (1_000 <= price <= 100_000):
            raise ValueError
    except ValueError:
        await update.message.reply_text("אנא הקלד מספר תקין, למשל: 7800")
        return SP_PRICE_CUSTOM

    chat_id = update.effective_chat.id
    await upsert_user(chat_id, max_price=price)
    user = await get_user(chat_id)
    await update.message.reply_text(
        _panel_text(user),
        parse_mode="Markdown",
        reply_markup=_panel_keyboard(user),
    )
    return SP_HOME


# ── broker sub-menu ───────────────────────────────────────────────────────────

async def cb_sp_broker(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    chat_id = query.from_user.id

    if value != "back":
        await upsert_user(chat_id, broker_filter=value)

    await _refresh_panel(query, chat_id)
    return SP_HOME


# ── build handler ──────────────────────────────────────────────────────────────

def build_settings_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("settings", cmd_settings),
            CommandHandler("status", cmd_settings),
            CommandHandler("setprice", cmd_settings),
            CommandHandler("setminprice", cmd_settings),
            CommandHandler("setrooms", cmd_settings),
            CommandHandler("setneighborhoods", cmd_settings),
            CommandHandler("setbroker", cmd_settings),
            CallbackQueryHandler(cb_sp_open, pattern=r"^sett:open$"),
        ],
        states={
            SP_HOME: [
                CallbackQueryHandler(cb_sp_action, pattern=r"^sp:(rooms|nbhd|price|broker|toggle)$"),
                CallbackQueryHandler(cb_sp_rooms, pattern=r"^sp_rooms:"),
                CallbackQueryHandler(cb_sp_nbhd, pattern=r"^sp_nbhd:"),
                CallbackQueryHandler(cb_sp_price, pattern=r"^sp_price:"),
                CallbackQueryHandler(cb_sp_broker, pattern=r"^sp_broker:"),
                CallbackQueryHandler(cb_sp_open, pattern=r"^sett:open$"),
            ],
            SP_ROOMS: [
                CallbackQueryHandler(cb_sp_rooms, pattern=r"^sp_rooms:"),
            ],
            SP_NBHD: [
                CallbackQueryHandler(cb_sp_nbhd, pattern=r"^sp_nbhd:"),
            ],
            SP_PRICE_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_sp_custom_price),
            ],
        },
        fallbacks=[],
        per_user=True,
        per_chat=False,
        name="settings_panel",
    )
