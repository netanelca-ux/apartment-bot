"""SQLite storage — listings deduplication + per-user settings."""
from __future__ import annotations

import json
import os

import aiosqlite

from config import DB_PATH

_DEFAULT_NEIGHBORHOODS = ["פלורנטין", "צפון פלורנטין", "לב העיר", "מרכז העיר", "נווה צדק"]


def _parse_rooms(value) -> list[float]:
    """Rooms is stored as JSON array or legacy float. Always return a list."""
    if value is None:
        return [2.0]
    if isinstance(value, (int, float)):
        return [float(value)]
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [float(r) for r in parsed]
        return [float(parsed)]
    except (ValueError, TypeError):
        return [2.0]


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id       INTEGER PRIMARY KEY,
                rooms         REAL    DEFAULT 2,
                min_price     INTEGER DEFAULT 4500,
                max_price     INTEGER DEFAULT 7200,
                neighborhoods TEXT    DEFAULT '[]',
                active        INTEGER DEFAULT 1,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_listings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL DEFAULT 0,
                source      TEXT    NOT NULL,
                listing_id  TEXT    NOT NULL,
                url         TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, source, listing_id)
            )
        """)
        await db.commit()


# ── user management ───────────────────────────────────────────────────────────

async def get_user(chat_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE chat_id = ?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    d = dict(row)
    d["neighborhoods"] = json.loads(d["neighborhoods"] or "[]") or _DEFAULT_NEIGHBORHOODS
    d["rooms"] = _parse_rooms(d.get("rooms"))
    return d


async def upsert_user(chat_id: int, **fields) -> None:
    if "neighborhoods" in fields and isinstance(fields["neighborhoods"], list):
        fields["neighborhoods"] = json.dumps(fields["neighborhoods"], ensure_ascii=False)
    if "rooms" in fields and isinstance(fields["rooms"], list):
        fields["rooms"] = json.dumps(fields["rooms"])
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{k} = excluded.{k}" for k in fields)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"INSERT INTO users (chat_id, {cols}) VALUES (?, {placeholders}) "
            f"ON CONFLICT(chat_id) DO UPDATE SET {updates}",
            (chat_id, *fields.values()),
        )
        await db.commit()


async def get_active_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE active = 1") as cur:
            rows = await cur.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["neighborhoods"] = json.loads(d["neighborhoods"] or "[]") or _DEFAULT_NEIGHBORHOODS
        d["rooms"] = _parse_rooms(d.get("rooms"))
        result.append(d)
    return result


# ── seen listings ─────────────────────────────────────────────────────────────

async def is_seen(chat_id: int, source: str, listing_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM seen_listings WHERE chat_id=? AND source=? AND listing_id=?",
            (chat_id, source, listing_id),
        ) as cur:
            return await cur.fetchone() is not None


async def mark_seen(chat_id: int, source: str, listing_id: str, url: str = "") -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO seen_listings (chat_id, source, listing_id, url) VALUES (?,?,?,?)",
            (chat_id, source, listing_id, url),
        )
        await db.commit()
