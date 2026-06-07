"""
Unified settings panel — all settings in one interactive message.
All callbacks are standalone (no ConversationHandler) so buttons always work.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from db.storage import get_user, upsert_user

logger = logging.getLogger(__name__)

ALL_ROOMS = ["1.5", "2", "2.5", "3", "3.5", "4+"]

ALL_NEIGHBORHOODS = [
    "פלורנטין",
    "צפון פלורנטין",
    "לב העיר / מרכז העיר",
    "הבימה",
    "נווה צדק",
    "כרם התימנים",
    "לוינסקי",
]

NEIGHBORHOOD_CANONICAL = {
    "פלורנטין": ["פלורנטין", "צפון פלורנטין"],
    "צפון פלורנטין": ["צפון פלורנטין", "פלורנטין"],
    "לב העיר / מרכז העיר": ["לב העיר", "מרכז העיר"],
    "הבימה": ["הבימה"],
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

async def cmd_settings(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await get_user(update.effective_chat.id)
    if user is None:
        await update.message.reply_text("אין לך עדיין פרופיל. שלח /start להגדרה.")
        return
    await update.message.reply_text(
        _panel_text(user),
        parse_mode="Markdown",
        reply_markup=_panel_keyboard(user),
    )


async def cb_sp_open(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Opens settings panel from the 'sett:open' button in the onboarding message."""
    query = update.callback_query
    await query.answer()
    await _refresh_panel(query, query.from_user.id)


# ── home actions ───────────────────────────────────────────────────────────────

async def cb_sp_action(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
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
        return

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
        return

    if action == "price":
        current_max = user.get("max_price", 7_200)
        await query.edit_message_text(
            "💰 *בחר מחיר מקסימלי לחודש:*",
            parse_mode="Markdown",
            reply_markup=_price_keyboard(current_max),
        )
        return

    if action == "broker":
        current = user.get("broker_filter", "no_broker")
        await query.edit_message_text(
            "🤝 *סינון תיווך:*",
            parse_mode="Markdown",
            reply_markup=_broker_keyboard(current),
        )
        return

    if action == "toggle":
        await upsert_user(chat_id, active=0 if user.get("active", 1) else 1)
        await _refresh_panel(query, chat_id)


# ── rooms sub-menu ─────────────────────────────────────────────────────────────

async def cb_sp_rooms(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    selected: list[str] = ctx.user_data.setdefault("sp_rooms", [])

    if value == "back":
        await _refresh_panel(query, query.from_user.id)
        return

    if value == "done":
        rooms_floats = [4.0 if r == "4+" else float(r) for r in selected] if selected else None
        await upsert_user(query.from_user.id, rooms=rooms_floats)
        await _refresh_panel(query, query.from_user.id)
        return

    if value == "all":
        selected.clear()
    elif value in selected:
        selected.remove(value)
    else:
        selected.append(value)

    await query.edit_message_reply_markup(reply_markup=_rooms_keyboard(selected))


# ── neighborhoods sub-menu ────────────────────────────────────────────────────

async def cb_sp_nbhd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    selected: list[str] = ctx.user_data.setdefault("sp_nbhd", [])

    if value == "back":
        await _refresh_panel(query, query.from_user.id)
        return

    if value == "done":
        if not selected:
            await query.answer("בחר לפחות אזור אחד", show_alert=True)
            return
        canonical: list[str] = []
        for n in selected:
            for c in NEIGHBORHOOD_CANONICAL.get(n, [n]):
                if c not in canonical:
                    canonical.append(c)
        await upsert_user(query.from_user.id, neighborhoods=canonical)
        await _refresh_panel(query, query.from_user.id)
        return

    if value in selected:
        selected.remove(value)
    else:
        selected.append(value)

    await query.edit_message_reply_markup(reply_markup=_nbhd_keyboard(selected))


# ── price sub-menu ─────────────────────────────────────────────────────────────

async def cb_sp_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    chat_id = query.from_user.id

    if value == "back":
        await _refresh_panel(query, chat_id)
        return

    if value == "custom":
        ctx.user_data["waiting_sp_price"] = True
        await query.edit_message_text(
            "💰 *הקלד מחיר מקסימלי לחודש:*\n\n_לדוגמה: 7800_",
            parse_mode="Markdown",
        )
        return

    try:
        await upsert_user(chat_id, max_price=int(value))
        await _refresh_panel(query, chat_id)
    except ValueError:
        pass


async def msg_sp_custom_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.user_data.get("waiting_sp_price"):
        return
    text = update.message.text.strip()
    try:
        price = int(text.replace(",", "").replace("₪", "").strip())
        if not (1_000 <= price <= 100_000):
            raise ValueError
    except ValueError:
        await update.message.reply_text("אנא הקלד מספר תקין, למשל: 7800")
        return

    ctx.user_data.pop("waiting_sp_price", None)
    chat_id = update.effective_chat.id
    await upsert_user(chat_id, max_price=price)
    user = await get_user(chat_id)
    await update.message.reply_text(
        _panel_text(user),
        parse_mode="Markdown",
        reply_markup=_panel_keyboard(user),
    )


# ── broker sub-menu ───────────────────────────────────────────────────────────

async def cb_sp_broker(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    chat_id = query.from_user.id

    if value != "back":
        await upsert_user(chat_id, broker_filter=value)

    await _refresh_panel(query, chat_id)


# ── register all handlers ─────────────────────────────────────────────────────

def register_settings_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("status", cmd_settings))
    app.add_handler(CommandHandler("setprice", cmd_settings))
    app.add_handler(CommandHandler("setminprice", cmd_settings))
    app.add_handler(CommandHandler("setrooms", cmd_settings))
    app.add_handler(CommandHandler("setneighborhoods", cmd_settings))
    app.add_handler(CommandHandler("setbroker", cmd_settings))
    app.add_handler(CallbackQueryHandler(cb_sp_open, pattern=r"^sett:open$"))
    app.add_handler(CallbackQueryHandler(cb_sp_action, pattern=r"^sp:(rooms|nbhd|price|broker|toggle)$"))
    app.add_handler(CallbackQueryHandler(cb_sp_rooms, pattern=r"^sp_rooms:"))
    app.add_handler(CallbackQueryHandler(cb_sp_nbhd, pattern=r"^sp_nbhd:"))
    app.add_handler(CallbackQueryHandler(cb_sp_price, pattern=r"^sp_price:"))
    app.add_handler(CallbackQueryHandler(cb_sp_broker, pattern=r"^sp_broker:"))
    # Text input for custom price — must be added AFTER ConversationHandlers
    # so onboarding DESCRIBE state still catches free-text during onboarding
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_sp_custom_price))
