import os, re, aiohttp, discord
from discord import app_commands
from discord.ext import commands

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
DEX_TOKENS = "https://api.dexscreener.com/latest/dex/tokens"
DEX_SEARCH = "https://api.dexscreener.com/latest/dex/search"

_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DECORATOR = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

class Market(commands.Cog):
    def __init__(self, bot): 
        self.bot = bot

    async def _fetch_pairs(self, session, query: str):
        """Try both token and search endpoints, return merged list."""
        pairs = []

        # If 0x address → tokens endpoint
        if ADDRESS_RE.match(query):
            url = f"{DEX_TOKENS}/{query}"
            try:
                async with session.get(url, timeout=20) as r:
                    if r.status == 200:
                        data = await r.json()
                        pairs.extend(data.get("pairs") or [])
            except Exception: 
                pass  # ignore and fallback to search

        # Always try search as well
        url = f"{DEX_SEARCH}?q={query}"
        async with session.get(url, timeout=20) as r:
            if r.status == 200:
                data = await r.json()
                extra = data.get("pairs") or data.get("results") or []
                pairs.extend([p for p in extra if isinstance(p, dict)])

        return pairs

    def _filter_by_chain(self, pairs):
        target = (os.getenv("DEXSCREENER_CHAIN") or "").lower().strip()
        if not target:
            return pairs
        filtered = [p for p in pairs if (p.get("chainId") or "").lower() == target]
        return filtered or pairs  # if filter removes all, fall back

    def _best_pair(self, pairs):
        if not pairs: return None
        def liq_usd(p):
            try: return float((p.get("liquidity") or {}).get("usd") or 0)
            except: return 0
        return max(pairs, key=liq_usd)

    def _embed_for_pair(self, p, title_hint=None):
        chain = p.get("chainId", "—")
        dex = p.get("dexId", "—")
        base = (p.get("baseToken") or {}).get("symbol", "—")
        quote = (p.get("quoteToken") or {}).get("symbol", "—")
        price_usd = p.get("priceUsd") or "—"
        price_native = p.get("priceNative") or "—"
        liq_usd = (p.get("liquidity") or {}).get("usd")
        vol_24h = (p.get("volume") or {}).get("h24")
        fdv = p.get("fdv")
        url = p.get("url")

        title = title_hint or f"{base}/{quote}"
        e = discord.Embed(title=f"💱 {title}", description=f"Chain: **{chain}** • DEX: **{dex}**")
        e.add_field(name="Price (USD)", value=f"${price_usd}", inline=True)
        e.add_field(name=f"Price ({quote})", value=f"{price_native}", inline=True)
        if isinstance(liq_usd, (int, float)):
            e.add_field(name="Liquidity (USD)", value=f"{liq_usd:,.0f}", inline=True)
        if isinstance(vol_24h, (int, float)):
            e.add_field(name="24h Volume (USD)", value=f"{vol_24h:,.0f}", inline=True)
        if isinstance(fdv, (int, float)):
            e.add_field(name="FDV (USD)", value=f"{fdv:,.0f}", inline=True)
        if url: e.url = url
        return e

    # ---- /price ----
    @GUILD_DECORATOR
    @app_commands.command(name="price", description="Get token price (default = PAL).")
    @app_commands.describe(query="0x address or token name (default PAL).")
    async def price(self, interaction: discord.Interaction, query: str | None = None):
        await interaction.response.defer(thinking=True)

        pal_addr = (os.getenv("PAL_TOKEN_ADDRESS") or "").strip()
        query = (query or pal_addr)

        if not query:
            return await interaction.followup.send("No query provided & PAL not set.", ephemeral=True)

        try:
            async with aiohttp.ClientSession() as session:
                pairs = await self._fetch_pairs(session, query)

            if not pairs:
                return await interaction.followup.send("❌ No pairs found for that input.", ephemeral=True)

            pairs = self._filter_by_chain(pairs)
            best = self._best_pair(pairs)
            if not best:
                return await interaction.followup.send("❌ No valid pairs after filtering.", ephemeral=True)

            await interaction.followup.send(embed=self._embed_for_pair(best, query))

        except Exception as e:
            await interaction.followup.send(f"⚠️ Error: {e}", ephemeral=True)

    # ---- /price_debug ----
    @GUILD_DECORATOR
    @app_commands.command(name="price_debug", description="List candidate pairs (ephemeral).")
    async def price_debug(self, interaction: discord.Interaction, query: str | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)

        pal_addr = (os.getenv("PAL_TOKEN_ADDRESS") or "").strip()
        query = (query or pal_addr)

        try:
            async with aiohttp.ClientSession() as session:
                pairs = await self._fetch_pairs(session, query)

            if not pairs:
                return await interaction.followup.send("No pairs returned.", ephemeral=True)

            lines = []
            for p in pairs[:10]:
                chain = p.get("chainId", "—")
                dex = p.get("dexId", "—")
                base = (p.get("baseToken") or {}).get("symbol", "—")
                quote = (p.get("quoteToken") or {}).get("symbol", "—")
                pair_addr = p.get("pairAddress", "—")
                lines.append(f"- {chain}/{dex}: **{base}/{quote}** — `{pair_addr}`")

            await interaction.followup.send("\n".join(lines), ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"⚠️ Error: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Market(bot))
