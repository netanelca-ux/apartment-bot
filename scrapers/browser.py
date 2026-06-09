from __future__ import annotations

from contextlib import asynccontextmanager
from playwright.async_api import async_playwright

LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-gpu",
    "--no-zygote",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--disable-sync",
    "--no-first-run",
    "--disable-background-networking",
    "--disable-breakpad",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--mute-audio",
    "--disable-blink-features=AutomationControlled",
]

_BLOCKED_TYPES = frozenset(["image", "media", "font"])

_STEALTH_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    "Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});"
    "Object.defineProperty(navigator, 'languages', {get: () => ['he-IL','he','en-US','en']});"
)


@asynccontextmanager
async def managed_browser():
    """Open a Chromium browser for the duration of a scan, then close it."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=LAUNCH_ARGS)
        try:
            yield browser
        finally:
            await browser.close()


async def new_page(browser, *, cookies: list[dict] | None = None):
    """Create a new context+page with stealth patches and resource blocking.

    Caller must call ``await page.context.close()`` when finished.
    """
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="he-IL",
        timezone_id="Asia/Jerusalem",
        extra_http_headers={"Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8"},
    )
    await context.add_init_script(_STEALTH_SCRIPT)
    if cookies:
        await context.add_cookies(cookies)

    page = await context.new_page()

    async def _route(route):
        if route.request.resource_type in _BLOCKED_TYPES:
            await route.abort()
        else:
            await route.continue_()

    await page.route("**/*", _route)
    return page
