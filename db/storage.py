import aiosqlite
import os
from config import DB_PATH


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seen_listings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source      TEXT NOT NULL,
                listing_id  TEXT NOT NULL,
                url         TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source, listing_id)
            )
        """)
        await db.commit()


async def is_seen(source: str, listing_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM seen_listings WHERE source = ? AND listing_id = ?",
            (source, listing_id),
        ) as cursor:
            return await cursor.fetchone() is not None


async def mark_seen(source: str, listing_id: str, url: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO seen_listings (source, listing_id, url) VALUES (?, ?, ?)",
            (source, listing_id, url),
        )
        await db.commit()
