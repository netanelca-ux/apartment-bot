"""Shared lightweight Facebook HTTP session — no browser required."""
from __future__ import annotations

import base64
import json
import logging
import os

import httpx

from config import FACEBOOK_COOKIES_FILE

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def get_cookies() -> dict[str, str]:
    raw = None
    if os.path.exists(FACEBOOK_COOKIES_FILE):
        with open(FACEBOOK_COOKIES_FILE) as f:
            raw = f.read()
        logger.info("Facebook session loaded from file")
    elif os.environ.get("FACEBOOK_COOKIES"):
        raw = base64.b64decode(os.environ["FACEBOOK_COOKIES"]).decode()
        logger.info("Facebook session loaded from env var")
    else:
        logger.warning("No Facebook session found")
        return {}

    data = json.loads(raw)
    return {c["name"]: c["value"] for c in data.get("cookies", [])}


def make_client(cookies: dict[str, str]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        cookies=cookies,
        headers=HEADERS,
        follow_redirects=True,
        timeout=30,
    )
