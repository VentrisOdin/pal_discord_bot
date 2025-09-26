import aiosqlite

DB_PATH = "pal_bot.sqlite"

class Settings:
    def __init__(self, path: str = DB_PATH):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""CREATE TABLE IF NOT EXISTS settings(
                k TEXT PRIMARY KEY,
                v TEXT NOT NULL
            )""")
            await db.commit()

    async def get(self, key: str, default=None):
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT v FROM settings WHERE k=?", (key,))
            row = await cur.fetchone()
            return row[0] if row else default

    async def set(self, key: str, value: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (key, str(value)),
            )
            await db.commit()
