"""Shared Playwright browser context for all scrapers."""
from __future__ import annotations

import base64
import json
import logging
import os

from playwright.async_api import async_playwright, Browser, BrowserContext, Playwright

from config import FACEBOOK_COOKIES_FILE

logger = logging.getLogger(__name__)

_playwright: Playwright | None = None
_browser: Browser | None = None
_context: BrowserContext | None = None


def _load_storage_state() -> dict | None:
    if os.path.exists(FACEBOOK_COOKIES_FILE):
        with open(FACEBOOK_COOKIES_FILE) as f:
            logger.info("Loaded saved Facebook session from file")
            return json.load(f)
    if os.environ.get("FACEBOOK_COOKIES"):
        raw = base64.b64decode(os.environ["FACEBOOK_COOKIES"]).decode()
        logger.info("Loaded saved Facebook session from environment variable")
        return json.loads(raw)
    logger.warning("No Facebook session found. Run tools/fb_login.py or set FACEBOOK_COOKIES env var.")
    return None


async def get_context() -> BrowserContext:
    global _playwright, _browser, _context

    # If browser crashed, reset everything
    if _browser is not None and not _browser.is_connected():
        logger.warning("Browser disconnected — recreating...")
        await close_browser()

    if _context is not None:
        return _context

    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--disable-gpu",
            "--single-process",
            "--memory-pressure-off",
        ],
    )

    context_options: dict = {
        "viewport": {"width": 1280, "height": 800},
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "locale": "he-IL",
        "timezone_id": "Asia/Jerusalem",
        "java_script_enabled": True,
    }

    storage = _load_storage_state()
    if storage:
        context_options["storage_state"] = storage

    _context = await _browser.new_context(**context_options)
    await _context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
    )
    return _context


async def reset_context() -> BrowserContext:
    """Force-close and recreate the browser context (call after a page crash)."""
    global _context
    if _context:
        try:
            await _context.close()
        except Exception:
            pass
        _context = None
    return await get_context()


async def close_browser():
    global _playwright, _browser, _context
    if _context:
        await _context.close()
        _context = None
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None
