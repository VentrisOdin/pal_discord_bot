# cogs/price_alerts.py
import os, re, time, aiohttp, aiosqlite, asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands

_GUILD_ID = int(os.getenv("GUILD_ID") or 0) or None
GUILD_DEC = app_commands.guilds(_GUILD_ID) if _GUILD_ID else (lambda f: f)
DB = "pal_bot.sqlite"

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
DEX_TOKENS = "https://api.dexscreener.com/latest/dex/tokens"
DEX_SEARCH = "https://api.dexscreener.com/latest/dex/search"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS price_alerts(
  user_id     INTEGER NOT NULL,
  address     TEXT    NOT NULL,
  above_usd   REAL,
  below_usd   REAL,
  enabled     INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(user_id, address)
);
"""

class PriceAlerts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None
        self._cache: dict[str, tuple[float, dict]] = {}

    async def cog_load(self):
        self._session = aiohttp.ClientSession()
        async with aiosqlite.connect(DB) as db:
            await db.execute(CREATE_SQL); await db.commit()
        if not self.check_prices.is_running():
            self.check_prices.start()

    def cog_unload(self):
        if self.check_prices.is_running(): self.check_prices.cancel()
        if self._session and not self._session.closed:
            asyncio.create_task(self._session.close())

    # -------------- helpers --------------
    def _cache_get(self, key): 
        exp, data = self._cache.get(key, (0,None))
        return data if exp > time.time() else None
    def _cache_set(self, key, data, ttl=45): 
        self._cache[key]=(time.time()+ttl, data)

    async def _get(self, url):
        cached = self._cache_get(f"GET:{url}")
        if cached is not None: return cached
        async with self._session.get(url, timeout=20) as r:
            r.raise_for_status()
            data = await r.json()
            self._cache_set(f"GET:{url}", data)
            return data

    async def _fetch_pairs(self, query: str):
        pairs = []
        if ADDRESS_RE.match(query):
            data = await self._get(f"{DEX_TOKENS}/{query}")
            pairs.extend(data.get("pairs") or [])
        data = await self._get(f"{DEX_SEARCH}?q={query}")
        pairs.extend((data.get("pairs") or data.get("results") or []))
        # keep dicts only
        return [p for p in pairs if isinstance(p, dict)]

    def _pick_best(self, pairs):
        if not pairs: return None
        def liq(p):
            try: return float((p.get("liquidity") or {}).get("usd") or 0)
            except: return 0
        return max(pairs, key=liq)

    async def _price_usd(self, query: str) -> float | None:
        pairs = await self._fetch_pairs(query)
        if not pairs: return None
        best = self._pick_best(pairs)
        try:
            return float(best.get("priceUsd"))
        except Exception:
            return None

    # -------------- commands --------------
    @GUILD_DEC
    @app_commands.command(name="alert_set", description="Set a price alert (USD).")
    @app_commands.describe(query="0x address or text (default PAL)", above="Alert if price >= X", below="Alert if price <= Y")
    async def alert_set(self, inter: discord.Interaction, query: str | None = None, above: float | None = None, below: float | None = None):
        addr = (query or os.getenv("PAL_TOKEN_ADDRESS") or "").strip()
        if not addr:
            return await inter.response.send_message("No query and PAL not set.", ephemeral=True)
        if above is None and below is None:
            return await inter.response.send_message("Provide at least one of `above` or `below`.", ephemeral=True)

        async with aiosqlite.connect(DB) as db:
            await db.execute("""INSERT INTO price_alerts(user_id,address,above_usd,below_usd,enabled)
                                VALUES (?,?,?,?,1)
                                ON CONFLICT(user_id,address)
                                DO UPDATE SET above_usd=excluded.above_usd, below_usd=excluded.below_usd, enabled=1""",
                             (inter.user.id, addr, above, below))
            await db.commit()

        await inter.response.send_message(f"🔔 Alert set for `{addr[:6]}…{addr[-4:] if addr.startswith('0x') else addr}` — "
                                          f"{'above '+str(above) if above is not None else ''} "
                                          f"{'below '+str(below) if below is not None else ''}".strip(),
                                          ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="alert_list", description="List your alerts.")
    async def alert_list(self, inter: discord.Interaction):
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT address, above_usd, below_usd, enabled FROM price_alerts WHERE user_id=?", (inter.user.id,))
            rows = await cur.fetchall()
        if not rows:
            return await inter.response.send_message("No alerts yet.", ephemeral=True)
        lines = [f"- `{a[:6]}…{a[-4:] if a.startswith('0x') else a}` • ≥ {au or '—'} • ≤ {bu or '—'} • {'on' if en else 'off'}"
                 for (a,au,bu,en) in rows]
        await inter.response.send_message("\n".join(lines), ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="alert_clear", description="Clear an alert.")
    @app_commands.describe(query="0x address or text (use same as when set)")
    async def alert_clear(self, inter: discord.Interaction, query: str):
        async with aiosqlite.connect(DB) as db:
            await db.execute("DELETE FROM price_alerts WHERE user_id=? AND address=?", (inter.user.id, query))
            await db.commit()
        await inter.response.send_message("🗑️ Alert cleared.", ephemeral=True)

    # -------------- loop --------------
    @tasks.loop(minutes=2.0)
    async def check_prices(self):
        try:
            async with aiosqlite.connect(DB) as db:
                cur = await db.execute("SELECT DISTINCT address FROM price_alerts WHERE enabled=1")
                addr_rows = await cur.fetchall()
            if not addr_rows: return

            for (addr,) in addr_rows:
                price = await self._price_usd(addr)
                if price is None: continue
                async with aiosqlite.connect(DB) as db:
                    cur = await db.execute("""SELECT user_id, above_usd, below_usd FROM price_alerts 
                                              WHERE enabled=1 AND address=?""", (addr,))
                    rows = await cur.fetchall()

                for uid, above, below in rows:
                    hit = (above is not None and price >= above) or (below is not None and price <= below)
                    if not hit: continue
                    user = self.bot.get_user(uid)
                    if user:
                        try:
                            await user.send(f"🔔 Price alert hit for `{addr[:6]}…{addr[-4:] if addr.startswith('0x') else addr}` — price: **${price:.6f}**")
                        except discord.Forbidden:
                            pass
                    # disable after trigger (one-shot). Remove this if you want persistent alerts.
                    async with aiosqlite.connect(DB) as db:
                        await db.execute("UPDATE price_alerts SET enabled=0 WHERE user_id=? AND address=?", (uid, addr))
                        await db.commit()
        except Exception:
            pass

async def setup(bot): await bot.add_cog(PriceAlerts(bot))
