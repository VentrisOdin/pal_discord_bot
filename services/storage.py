import aiosqlite
from datetime import datetime, timezone

DB_PATH = "pal_bot.sqlite"

CREATE_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS wallets(
    user_id TEXT PRIMARY KEY,
    wallet  TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seen_events(
    source   TEXT NOT NULL,
    event_id TEXT NOT NULL,
    seen_at  TEXT NOT NULL,
    PRIMARY KEY (source, event_id)
);
"""

class Storage:
    def __init__(self, path: str = DB_PATH):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            for stmt in CREATE_SQL.strip().split(";"):
                st = stmt.strip()
                if st:
                    await db.execute(st)
            await db.commit()

    async def mark_seen(self, source: str, eid: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO seen_events(source,event_id,seen_at) VALUES(?,?,?)",
                (source, eid, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    async def is_seen(self, source: str, eid: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT 1 FROM seen_events WHERE source=? AND event_id=?",
                (source, eid),
            )
            return (await cur.fetchone()) is not None

    async def upsert_wallet(self, user_id: int, wallet: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO wallets(user_id, wallet, verified, created_at)
                   VALUES (?, ?, 0, ?)
                   ON CONFLICT(user_id) DO UPDATE SET wallet=excluded.wallet""",
                (str(user_id), wallet, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()

    async def get_wallet(self, user_id: int):
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT wallet, verified FROM wallets WHERE user_id=?",
                (str(user_id),),
            )
            return await cur.fetchone()

    async def set_verified(self, user_id: int, verified: bool):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE wallets SET verified=? WHERE user_id=?",
                (1 if verified else 0, str(user_id)),
            )
            await db.commit()

    async def clear_seen(self):
        """Clear all seen disaster items from the database."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM seen_events")
            await db.commit()
