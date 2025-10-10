import aiosqlite
import logging
from typing import Optional

class UserPrefs:
    def __init__(self, db_path: str = "data/pal_bot.sqlite"):
        self.db_path = db_path

    async def init(self):
        """Initialize the user preferences table."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_prefs (
                    user_id INTEGER,
                    guild_id INTEGER,
                    dm_opt_out INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)
            await db.commit()
            logging.info("UserPrefs: initialized")

    async def set_dm_opt_out(self, user_id: int, guild_id: int, opt_out: bool = True):
        """Set DM opt-out preference for a user."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO user_prefs (user_id, guild_id, dm_opt_out)
                VALUES (?, ?, ?)
            """, (user_id, guild_id, int(opt_out)))
            await db.commit()

    async def is_dm_opt_out(self, user_id: int, guild_id: int) -> bool:
        """Check if user has opted out of DMs."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT dm_opt_out FROM user_prefs 
                WHERE user_id = ? AND guild_id = ?
            """, (user_id, guild_id)) as cursor:
                row = await cursor.fetchone()
                return bool(row[0]) if row else False