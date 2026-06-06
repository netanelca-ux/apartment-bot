"""
בוט חיפוש דירות — נקודת כניסה ראשית.

מריץ סורקים מתוזמנים ומשלח התראות לטלגרם על מודעות חדשות.
תומך בפקודות טלגרם לשליטה ישירה מהצ'אט.
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
from db.storage import init_db, is_seen, mark_seen
from scrapers.browser import close_browser, get_context
from scrapers import yad2, fb_marketplace, fb_groups
from scrapers.filters import passes_filters

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("main")


# ── core job logic ────────────────────────────────────────────────────────────

async def process_listings(listings: list[dict]):
    new_count = 0
    for listing in listings:
        source = listing["source"]
        listing_id = listing["listing_id"]
        if not listing_id:
            continue
        if not passes_filters(listing):
            continue
        if await is_seen(source, listing_id):
            continue
        try:
            await send_listing(listing)
            await mark_seen(source, listing_id, listing.get("url", ""))
            new_count += 1
        except Exception as e:
            logger.error(f"Failed to send/record listing {listing_id}: {e}")
    return new_count


# ── scheduled jobs ────────────────────────────────────────────────────────────

async def job_yad2():
    if commands.is_paused():
        return
    logger.info("⏱  Starting Yad2 scan...")
    try:
        ctx = await get_context()
        listings = await yad2.fetch_listings(ctx)
        count = await process_listings(listings)
        logger.info(f"✅ Yad2 done — {len(listings)} found, {count} new")
    except Exception as e:
        logger.error(f"Yad2 job failed: {e}")


async def job_fb_marketplace():
    if commands.is_paused():
        return
    logger.info("⏱  Starting Facebook Marketplace scan...")
    try:
        ctx = await get_context()
        listings = await fb_marketplace.fetch_listings(ctx)
        count = await process_listings(listings)
        logger.info(f"✅ FB Marketplace done — {len(listings)} found, {count} new")
    except Exception as e:
        logger.error(f"FB Marketplace job failed: {e}")


async def job_fb_groups():
    if commands.is_paused():
        return
    logger.info("⏱  Starting Facebook Groups scan...")
    try:
        ctx = await get_context()
        listings = await fb_groups.fetch_listings(ctx)
        count = await process_listings(listings)
        logger.info(f"✅ FB Groups done — {len(listings)} found, {count} new")
    except Exception as e:
        logger.error(f"FB Groups job failed: {e}")


async def scan_all():
    """Run all scrapers once — called by the /scan Telegram command."""
    await job_yad2()
    await job_fb_marketplace()
    await job_fb_groups()


# ── startup checks ────────────────────────────────────────────────────────────

def _check_config():
    missing = []
    if not config.TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not config.TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        logger.error(f"Missing required env vars: {', '.join(missing)}")
        sys.exit(1)


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    _check_config()
    await init_db()

    logger.info("🚀 Apartment bot starting...")
    logger.info(f"   Criteria: {config.SEARCH_CRITERIA['rooms']} rooms | "
                f"up to {config.SEARCH_CRITERIA['max_price']}₪ | "
                f"{', '.join(config.SEARCH_CRITERIA['neighborhoods'])}")

    # Wire up the /scan command callback
    commands.set_scan_callback(scan_all)

    # Build Telegram Application for receiving commands
    tg_app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    tg_app.add_handler(CommandHandler("help", commands.cmd_help))
    tg_app.add_handler(CommandHandler("start", commands.cmd_help))
    tg_app.add_handler(CommandHandler("status", commands.cmd_status))
    tg_app.add_handler(CommandHandler("scan", commands.cmd_scan))
    tg_app.add_handler(CommandHandler("setprice", commands.cmd_setprice))
    tg_app.add_handler(CommandHandler("setminprice", commands.cmd_setminprice))
    tg_app.add_handler(CommandHandler("setrooms", commands.cmd_setrooms))
    tg_app.add_handler(CommandHandler("pause", commands.cmd_pause))
    tg_app.add_handler(CommandHandler("resume", commands.cmd_resume))

    # Run initial scan before starting the loop
    await scan_all()

    await send_status(
        "🤖 בוט חיפוש דירות פעיל!\n"
        f"מחפש {config.SEARCH_CRITERIA['rooms']} חדרים עד "
        f"{config.SEARCH_CRITERIA['max_price']:,}₪ ב"
        + "‎, ".join(config.SEARCH_CRITERIA["neighborhoods"])
        + "\n\nשלח /help לרשימת הפקודות"
    )

    # Schedule recurring scans
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

    # Start Telegram polling (non-blocking — runs in the background)
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling(drop_pending_updates=True)
    logger.info("📨 Telegram command polling started")

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
