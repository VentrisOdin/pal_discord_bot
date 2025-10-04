# cogs/sources_admin.py
import os
import discord
from discord.ext import commands
from discord import app_commands

from services.settings import Settings

_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

SOURCES = [
    ("ENABLE_USGS", "USGS Earthquakes"),
    ("ENABLE_RELIEFWEB", "ReliefWeb Reports"),
    ("ENABLE_RW_DISASTERS", "ReliefWeb Disasters"),
    ("ENABLE_EONET", "NASA EONET"),
    ("ENABLE_GDACS_JSON", "GDACS (JSON)"),
    ("ENABLE_GDACS", "GDACS (RSS legacy)"),
    ("ENABLE_COPERNICUS", "Copernicus EMS"),
    ("ENABLE_WHO", "WHO Outbreaks"),
    ("ENABLE_FIRMS", "NASA FIRMS"),
]

def _to_bool_str(v: bool) -> str:
    return "true" if v else "false"

class SourcesAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings = Settings()

    async def cog_load(self):
        await self.settings.init()

    # ---- helpers ----
    async def _set(self, key: str, value: str):
        await self.settings.set(key, value)

    async def _get(self, key: str, default: str | None = None) -> str | None:
        return await self.settings.get(key, default)

    # ---- /sources show ----
    @GUILD_DEC
    @app_commands.command(name="sources_show", description="(Staff) Show current source toggles and key thresholds.")
    async def sources_show(self, inter: discord.Interaction):
        if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
            return await inter.response.send_message("🚫 Manage Server required.", ephemeral=True)

        # Fetch toggles; fall back to env if missing in DB
        lines = []
        for key, label in SOURCES:
            env_default = os.getenv(key, "true" if "GDACS" not in key else "true" if key.endswith("_JSON") else "false")
            v = await self._get(key, env_default)
            lines.append(f"- **{label}**: `{v}` ({key})")

        usgs_min = await self._get("USGS_MIN_MAG", os.getenv("USGS_MIN_MAG", "5.0"))
        usgs_ping = await self._get("USGS_PING_MAG", os.getenv("USGS_PING_MAG", "6.8"))
        poll = await self._get("DISASTER_POLL_MINUTES", os.getenv("DISASTER_POLL_MINUTES", "5"))
        digest = await self._get("DIGEST_TIME_UTC", os.getenv("DIGEST_TIME_UTC", "09:00"))
        firms_url = await self._get("FIRMS_URL", os.getenv("FIRMS_URL", ""))

        e = discord.Embed(title="🌐 Source Toggles", color=discord.Color.blurple())
        e.add_field(name="Feeds", value="\n".join(lines), inline=False)
        e.add_field(name="USGS_MIN_MAG", value=usgs_min, inline=True)
        e.add_field(name="USGS_PING_MAG", value=usgs_ping, inline=True)
        e.add_field(name="DISASTER_POLL_MINUTES", value=poll, inline=True)
        e.add_field(name="DIGEST_TIME_UTC", value=digest, inline=True)
        e.add_field(name="FIRMS_URL", value=firms_url or "—", inline=False)

        await inter.response.send_message(embed=e, ephemeral=True)

    # ---- /sources enable ----
    @GUILD_DEC
    @app_commands.command(name="sources_enable", description="(Staff) Enable a data source.")
    @app_commands.describe(source_key="Which source to enable (e.g., ENABLE_USGS)")
    async def sources_enable(self, inter: discord.Interaction, source_key: str):
        if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
            return await inter.response.send_message("🚫 Manage Server required.", ephemeral=True)
        keys = {k for k, _ in SOURCES}
        if source_key not in keys:
            return await inter.response.send_message(f"Unknown key. Try one of: {', '.join(sorted(keys))}", ephemeral=True)
        await self._set(source_key, "true")
        await inter.response.send_message(f"✅ `{source_key}` set to `true`.", ephemeral=True)

    # ---- /sources_disable ----
    @GUILD_DEC
    @app_commands.command(name="sources_disable", description="(Staff) Disable a data source.")
    @app_commands.describe(source_key="Which source to disable (e.g., ENABLE_WHO)")
    async def sources_disable(self, inter: discord.Interaction, source_key: str):
        if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
            return await inter.response.send_message("🚫 Manage Server required.", ephemeral=True)
        keys = {k for k, _ in SOURCES}
        if source_key not in keys:
            return await inter.response.send_message(f"Unknown key. Try one of: {', '.join(sorted(keys))}", ephemeral=True)
        await self._set(source_key, "false")
        await inter.response.send_message(f"✅ `{source_key}` set to `false`.", ephemeral=True)

    # ---- /sources_set (thresholds & times) ----
    @GUILD_DEC
    @app_commands.command(name="sources_set", description="(Staff) Set USGS thresholds, poll minutes, digest time, FIRMS URL.")
    @app_commands.describe(
        usgs_min_mag="Min magnitude for USGS posts (e.g., 5.0)",
        usgs_ping_mag="Magnitude that triggers role ping (e.g., 6.8)",
        poll_minutes="Poll interval in minutes (e.g., 5)",
        digest_time_utc="Daily digest time (UTC HH:MM, e.g., 09:00)",
        firms_url="Optional public FIRMS data URL (CSV/GeoJSON)"
    )
    async def sources_set(
        self,
        inter: discord.Interaction,
        usgs_min_mag: float | None = None,
        usgs_ping_mag: float | None = None,
        poll_minutes: int | None = None,
        digest_time_utc: str | None = None,
        firms_url: str | None = None,
    ):
        if not (inter.user.guild_permissions.manage_guild or inter.user.guild_permissions.administrator):
            return await inter.response.send_message("🚫 Manage Server required.", ephemeral=True)

        changed = []
        if usgs_min_mag is not None:
            await self._set("USGS_MIN_MAG", str(usgs_min_mag))
            changed.append(f"USGS_MIN_MAG={usgs_min_mag}")
        if usgs_ping_mag is not None:
            await self._set("USGS_PING_MAG", str(usgs_ping_mag))
            changed.append(f"USGS_PING_MAG={usgs_ping_mag}")
        if poll_minutes is not None:
            await self._set("DISASTER_POLL_MINUTES", str(max(1, poll_minutes)))
            changed.append(f"DISASTER_POLL_MINUTES={max(1, poll_minutes)}")
        if digest_time_utc is not None:
            await self._set("DIGEST_TIME_UTC", digest_time_utc)
            changed.append(f"DIGEST_TIME_UTC={digest_time_utc}")
        if firms_url is not None:
            await self._set("FIRMS_URL", firms_url)
            changed.append(f"FIRMS_URL={(firms_url or '—')}")

        if not changed:
            return await inter.response.send_message("No changes provided.", ephemeral=True)

        await inter.response.send_message("✅ Updated:\n• " + "\n• ".join(changed) + "\n\n*(Changes take effect immediately in the next poll/digest tick.)*", ephemeral=True)

async def setup(bot):
    await bot.add_cog(SourcesAdmin(bot))
