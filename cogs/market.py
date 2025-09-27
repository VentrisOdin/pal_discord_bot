# cogs/market.py
import os
import re
import math
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

DEX_TOKENS = "https://api.dexscreener.com/latest/dex/tokens"
DEX_SEARCH = "https://api.dexscreener.com/latest/dex/search"

# Optional fast guild scope
_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

def fmt_num(x) -> str:
    try:
        x = float(x)
    except Exception:
        return "—"
    if math.isnan(x) or math.isinf(x):
        return "—"
    if x >= 1_000_000_000:
        return f"{x/1_000_000_000:.2f}B"
    if x >= 1_000_000:
        return f"{x/1_000_000:.2f}M"
    if x >= 1_000:
        return f"{x/1_000:.2f}K"
    return f"{x:.6f}".rstrip("0").rstrip(".")

def make_embed_for_pair(p: dict, title_hint: str | None = None) -> discord.Embed:
    chain = (p.get("chainId") or "—").upper()
    dex = p.get("dexId") or "—"
    base_tok = (p.get("baseToken") or {}).get("symbol") or "—"
    quote_tok = (p.get("quoteToken") or {}).get("symbol") or "—"
    price_usd = p.get("priceUsd")
    price_native = p.get("priceNative")
    liq = (p.get("liquidity") or {}).get("usd")
    vol24 = (p.get("volume") or {}).get("h24")
    fdv = p.get("fdv")
    url = p.get("url")
    pair_addr = p.get("pairAddress")

    title = title_hint or f"{base_tok}/{quote_tok}"
    e = discord.Embed(
        title=f"💱 {title}",
        description=f"Chain **{chain}** • DEX **{dex}**",
        color=discord.Color.blurple()
    )
    e.add_field(name="Price (USD)", value=f"${fmt_num(price_usd)}", inline=True)
    if quote_tok and price_native:
        e.add_field(name=f"Price ({quote_tok})", value=fmt_num(price_native), inline=True)
    e.add_field(name="Liquidity", value=f"${fmt_num(liq)}", inline=True)
    e.add_field(name="24h Volume", value=f"${fmt_num(vol24)}", inline=True)
    if isinstance(fdv, (int, float)):
        e.add_field(name="FDV", value=f"${fmt_num(fdv)}", inline=True)
    if pair_addr:
        e.add_field(name="Pair", value=f"`{pair_addr}`", inline=False)
    if url:
        e.url = url
    e.set_footer(text="Data: DexScreener")
    return e

class Market(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache: dict[str, tuple[float, dict]] = {}  # key -> (exp_ts, data)

    # -------- tiny cache (45s) --------
    def _cache_get(self, key: str):
        import time
        v = self._cache.get(key)
        if not v:
            return None
        exp, data = v
        return data if exp > time.time() else None

    def _cache_set(self, key: str, data: dict, ttl: int = 45):
        import time
        self._cache[key] = (time.time() + ttl, data)

    async def _get_json(self, session: aiohttp.ClientSession, url: str):
        cached = self._cache_get(f"GET:{url}")
        if cached is not None:
            return cached
        async with session.get(url, timeout=20) as r:
            r.raise_for_status()
            data = await r.json()
            self._cache_set(f"GET:{url}", data)
            return data

    # -------- helpers --------
    def _filter_chain(self, pairs: list[dict]) -> list[dict]:
        target = (os.getenv("DEXSCREENER_CHAIN") or "").lower().strip()
        if not target:
            return pairs
        filtered = [p for p in pairs if (p.get("chainId") or "").lower() == target]
        return filtered or pairs  # fallback to all if none match

    def _best_pair(self, pairs: list[dict]) -> dict | None:
        if not pairs:
            return None
        def liq_usd(p):
            try:
                return float((p.get("liquidity") or {}).get("usd") or 0)
            except Exception:
                return 0.0
        return max(pairs, key=liq_usd)

    # -------- /price --------
    @GUILD_DEC
    @app_commands.command(name="price", description="Token price from DexScreener.")
    @app_commands.describe(query="0x address or search text (defaults to PAL).")
    @app_commands.checks.cooldown(1, 3.0)
    async def price(self, interaction: discord.Interaction, query: str | None = None):
        await interaction.response.defer(thinking=True)
        pal_addr = (os.getenv("PAL_TOKEN_ADDRESS") or "").strip()
        query = (query or pal_addr).strip()

        if not query:
            return await interaction.followup.send(
                "Provide a token **address** (0x…) or a search term, "
                "or set `PAL_TOKEN_ADDRESS` in `.env`.", ephemeral=True
            )

        try:
            async with aiohttp.ClientSession() as s:
                if ADDRESS_RE.match(query):
                    data = await self._get_json(s, f"{DEX_TOKENS}/{query}")
                    pairs = data.get("pairs") or []
                    title_hint = f"{query[:6]}…{query[-4:]}"
                else:
                    data = await self._get_json(s, f"{DEX_SEARCH}?q={query}")
                    # API returns "pairs" (modern) or "results" (legacy); normalize & filter dicts
                    pairs = data.get("pairs") or data.get("results") or []
                    pairs = [p for p in pairs if isinstance(p, dict)]

                if not pairs:
                    # Helpful guidance instead of a dead end
                    tip = (
                        "No pairs found. Try:\n"
                        "• Paste the **contract address** (0x…)\n"
                        "• Use `/price_debug` to inspect candidates\n"
                        "• Check your `DEXSCREENER_CHAIN` in `.env`"
                    )
                    return await interaction.followup.send(tip, ephemeral=True)

                pairs = self._filter_chain(pairs)
                best = self._best_pair(pairs)
                if not best:
                    return await interaction.followup.send("No liquid pairs after filtering.", ephemeral=True)

                title_hint = title_hint if ADDRESS_RE.match(query) else (
                    f"{(best.get('baseToken') or {}).get('symbol','?')}/{(best.get('quoteToken') or {}).get('symbol','?')}"
                )
                embed = make_embed_for_pair(best, title_hint=title_hint)
                await interaction.followup.send(embed=embed)

        except app_commands.CommandOnCooldown:
            raise
        except Exception as e:
            await interaction.followup.send(f"Error fetching price: {e}", ephemeral=True)

    # -------- /price_debug --------
    @GUILD_DEC
    @app_commands.command(name="price_debug", description="Show candidate pairs (ephemeral).")
    @app_commands.describe(query="0x address or search text (defaults to PAL).")
    async def price_debug(self, interaction: discord.Interaction, query: str | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        pal_addr = (os.getenv("PAL_TOKEN_ADDRESS") or "").strip()
        query = (query or pal_addr).strip()
        if not query:
            return await interaction.followup.send("Need an address or search term.", ephemeral=True)

        try:
            async with aiohttp.ClientSession() as s:
                if ADDRESS_RE.match(query):
                    data = await self._get_json(s, f"{DEX_TOKENS}/{query}")
                    pairs = data.get("pairs") or []
                else:
                    data = await self._get_json(s, f"{DEX_SEARCH}?q={query}")
                    pairs = data.get("pairs") or data.get("results") or []
                    pairs = [p for p in pairs if isinstance(p, dict)]

            if not pairs:
                return await interaction.followup.send("No pairs returned by DexScreener.", ephemeral=True)

            pairs = self._filter_chain(pairs)

            # show up to 12 candidates
            lines = []
            for p in pairs[:12]:
                chain = p.get("chainId", "—")
                dex = p.get("dexId", "—")
                base = (p.get("baseToken") or {}).get("symbol", "—")
                quote = (p.get("quoteToken") or {}).get("symbol", "—")
                pair_addr = p.get("pairAddress", "—")
                liq = (p.get("liquidity") or {}).get("usd")
                lines.append(f"- {chain}/{dex}: **{base}/{quote}** — `{pair_addr}` — Liq ${fmt_num(liq)}")

            txt = "Candidates (filtered):\n" + "\n".join(lines)
            await interaction.followup.send(txt, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Market(bot))
