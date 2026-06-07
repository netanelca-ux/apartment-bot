"""
בוט חיפוש דירות — נקודת כניסה ראשית.

מריץ סורקים מתוזמנים ומשלח התראות לטלגרם על מודעות חדשות.
כל משתמש מקבל התראות לפי הגדרות אישיות שלו.
"""
import asyncio
import logging
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from telegram.ext import Application, CommandHandler

import config
from bot.notifier import send_listing, send_status
from bot import commands
from bot.onboarding import build_conversation_handler
from bot.settings_panel import register_settings_handlers
from db.storage import init_db, is_seen, mark_seen, get_active_users, get_user, upsert_user
from scrapers.browser import close_browser, get_context
from scrapers import yad2, fb_marketplace, fb_groups, yad2_scrapingbee
from scrapers.filters import passes_filters

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("main")


# ── core job logic ────────────────────────────────────────────────────────────

def _user_criteria(user: dict) -> dict:
    # rooms is always a list[float] after db/storage._parse_rooms
    return {
        "min_price": user.get("min_price", 0),
        "max_price": user.get("max_price", config.SEARCH_CRITERIA["max_price"]),
        "rooms": user.get("rooms") or None,
        "neighborhoods": user.get("neighborhoods", config.SEARCH_CRITERIA["neighborhoods"]),
        "broker_filter": user.get("broker_filter", "no_broker"),
        "require_price": config.SEARCH_CRITERIA.get("require_price", True),
    }


def _listing_matches_neighborhood(listing: dict, neighborhoods: list[str]) -> bool:
    text = " ".join([
        str(listing.get("neighborhood", "")),
        str(listing.get("city", "")),
        str(listing.get("address", "")),
        str(listing.get("title", "")),
        str(listing.get("description", "")),
    ]).lower()
    return any(n.lower() in text for n in neighborhoods)


async def process_listings(listings: list[dict]):
    users = await get_active_users()
    if not users:
        logger.info("No active users — skipping fan-out")
        return

    new_total = 0
    for listing in listings:
        source = listing.get("source", "")
        listing_id = listing.get("listing_id", "")
        if not listing_id:
            continue

        for user in users:
            chat_id: int = user["chat_id"]
            criteria = _user_criteria(user)

            if not passes_filters(listing, criteria):
                continue

            # Only apply neighborhood check when the listing has no neighborhood field
            # (scrapers already filter by neighborhood; this catches edge cases)
            if not listing.get("neighborhood") and not _listing_matches_neighborhood(listing, criteria["neighborhoods"]):
                continue

            if await is_seen(chat_id, source, listing_id):
                continue

            try:
                await send_listing(listing, chat_id)
                await mark_seen(chat_id, source, listing_id, listing.get("url", ""))
                new_total += 1
            except Exception as e:
                logger.error(f"Failed to send listing {listing_id} to {chat_id}: {e}")

    if new_total:
        logger.info(f"Sent {new_total} new listing notifications across all users")


# ── scheduled jobs ────────────────────────────────────────────────────────────

async def job_yad2():
    if commands.is_paused():
        return
    logger.info("⏱  Starting Yad2 scan...")
    try:
        if config.SCRAPINGBEE_API_KEY:
            listings = await yad2_scrapingbee.fetch_listings(config.SCRAPINGBEE_API_KEY)
        else:
            ctx = await get_context()
            listings = await yad2.fetch_listings(ctx)
        await process_listings(listings)
        logger.info(f"✅ Yad2 done — {len(listings)} found")
    except Exception as e:
        logger.error(f"Yad2 job failed: {e}")


async def job_fb_marketplace():
    if commands.is_paused():
        return
    logger.info("⏱  Starting Facebook Marketplace scan...")
    try:
        ctx = await get_context()
        listings = await fb_marketplace.fetch_listings(ctx)
        await process_listings(listings)
        logger.info(f"✅ FB Marketplace done — {len(listings)} found")
    except Exception as e:
        logger.error(f"FB Marketplace job failed: {e}")


async def job_fb_groups():
    if commands.is_paused():
        return
    logger.info("⏱  Starting Facebook Groups scan...")
    try:
        ctx = await get_context()
        listings = await fb_groups.fetch_listings(ctx)
        await process_listings(listings)
        logger.info(f"✅ FB Groups done — {len(listings)} found")
    except Exception as e:
        logger.error(f"FB Groups job failed: {e}")


async def scan_all():
    """Run all scrapers once — called by the /scan Telegram command."""
    await job_yad2()
    await job_fb_marketplace()
    await job_fb_groups()


# ── startup checks ────────────────────────────────────────────────────────────

def _check_config():
    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("Missing required env var: TELEGRAM_BOT_TOKEN")
        sys.exit(1)


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    _check_config()
    await init_db()

    logger.info("🚀 Apartment bot starting...")

    # Auto-register the owner so the bot works even if /start was never sent
    # (or after a DB reset on Railway redeploy)
    if config.OWNER_CHAT_ID:
        owner_id = int(config.OWNER_CHAT_ID)
        if not await get_user(owner_id):
            c = config.SEARCH_CRITERIA
            await upsert_user(
                owner_id,
                rooms=None,
                min_price=c.get("min_price", 0),
                max_price=c["max_price"],
                neighborhoods=c["neighborhoods"],
                active=1,
            )
            logger.info(f"Auto-registered owner {owner_id} with default search criteria")

    commands.set_scan_callback(scan_all)

    tg_app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # ConversationHandlers first, then standalone (order matters for text handlers)
    tg_app.add_handler(build_conversation_handler())
    register_settings_handlers(tg_app)

    # Standalone commands
    tg_app.add_handler(CommandHandler("help", commands.cmd_help))
    tg_app.add_handler(CommandHandler("scan", commands.cmd_scan))
    tg_app.add_handler(CommandHandler("pause", commands.cmd_pause))
    tg_app.add_handler(CommandHandler("resume", commands.cmd_resume))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(job_yad2, IntervalTrigger(seconds=config.YAD2_POLL_INTERVAL),
                      id="yad2", max_instances=1, coalesce=True)
    scheduler.add_job(job_fb_marketplace, IntervalTrigger(seconds=config.FACEBOOK_POLL_INTERVAL),
                      id="fb_marketplace", max_instances=1, coalesce=True)
    scheduler.add_job(job_fb_groups, IntervalTrigger(seconds=config.FACEBOOK_POLL_INTERVAL),
                      id="fb_groups", max_instances=1, coalesce=True)
    scheduler.start()
    logger.info(f"📅 Scheduler running — Yad2 every {config.YAD2_POLL_INTERVAL // 60}m, "
                f"Facebook every {config.FACEBOOK_POLL_INTERVAL // 60}m")

    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling(drop_pending_updates=True)
    logger.info("📨 Telegram command polling started")

    # Initial scan runs in the background so Telegram polling is ready immediately
    asyncio.create_task(scan_all())

    if config.OWNER_CHAT_ID:
        await send_status(
            "🤖 בוט חיפוש דירות עלה לאוויר!\n"
            "משתמשים חדשים יכולים להקליד /start כדי להגדיר חיפוש אישי.\n\n"
            "שלח /help לרשימת הפקודות."
        )

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
        scheduler.shutdown(wait=False)
        await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()
        await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
