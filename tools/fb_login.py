#!/usr/bin/env python3
"""
כלי להתחברות ידנית לפייסבוק ושמירת ה-session.

הרץ פעם אחת לפני שמפעילים את הבוט הראשי:
    python tools/fb_login.py

יפתח חלון דפדפן — התחבר לחשבון הפייסבוק שלך ידנית.
לאחר ההתחברות, לחץ Enter בטרמינל — ה-session נשמר אוטומטית.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from playwright.async_api import async_playwright
from config import FACEBOOK_COOKIES_FILE


async def main():
    print("=" * 60)
    print("כלי התחברות לפייסבוק")
    print("=" * 60)
    print()
    print("פותח דפדפן... התחבר לחשבון הפייסבוק שלך.")
    print("לאחר ההתחברות המלאה, חזור לחלון זה ולחץ Enter.")
    print()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # חלון גלוי כדי שתוכל להתחבר
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="he-IL",
        )

        page = await context.new_page()
        await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")

        print("✅ הדפדפן נפתח. התחבר לפייסבוק ואז חזור לכאן.")
        print()
        input("לאחר ההתחברות, לחץ Enter כדי לשמור את ה-session... ")

        # Save session state
        os.makedirs(os.path.dirname(FACEBOOK_COOKIES_FILE) or ".", exist_ok=True)
        storage = await context.storage_state()

        with open(FACEBOOK_COOKIES_FILE, "w") as f:
            json.dump(storage, f, indent=2)

        print(f"\n✅ Session נשמר ל: {FACEBOOK_COOKIES_FILE}")
        print("עכשיו אפשר להפעיל את הבוט הראשי: python main.py")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
