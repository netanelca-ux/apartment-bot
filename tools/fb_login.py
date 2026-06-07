#!/usr/bin/env python3
"""
כלי להתחברות ידנית לפייסבוק ושמירת ה-session.

הרץ פעם אחת לחידוש הקוקיז:
    python tools/fb_login.py

יפתח חלון דפדפן — התחבר לחשבון הפייסבוק שלך ידנית.
לאחר ההתחברות, לחץ Enter בטרמינל — ה-session נשמר ומועלה ל-Railway אוטומטית.
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from playwright.async_api import async_playwright
from config import FACEBOOK_COOKIES_FILE


def _upload_to_railway(cookies_path: str) -> bool:
    railway = shutil.which("railway") or os.path.expanduser("~/.railway/bin/railway")
    if not os.path.exists(railway):
        print("⚠️  Railway CLI לא נמצא — דלג על העלאה אוטומטית.")
        return False

    with open(cookies_path) as f:
        raw = f.read()
    encoded = base64.b64encode(raw.encode()).decode()

    result = subprocess.run(
        [railway, "variable", "set", f"FACEBOOK_COOKIES={encoded}"],
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    if result.returncode == 0:
        print("✅ Railway עודכן עם הקוקיז החדשים.")
        return True
    else:
        print(f"⚠️  שגיאה בעדכון Railway: {result.stderr.strip()}")
        return False


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
            headless=False,
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

        os.makedirs(os.path.dirname(FACEBOOK_COOKIES_FILE) or ".", exist_ok=True)
        storage = await context.storage_state()

        with open(FACEBOOK_COOKIES_FILE, "w") as f:
            json.dump(storage, f, indent=2)

        print(f"\n✅ Session נשמר ל: {FACEBOOK_COOKIES_FILE}")

        await browser.close()

    _upload_to_railway(FACEBOOK_COOKIES_FILE)


if __name__ == "__main__":
    asyncio.run(main())
