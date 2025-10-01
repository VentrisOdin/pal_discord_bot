# cogs/settings_admin.py
import os
import discord
from discord import app_commands
from discord.ext import commands
from services.settings import Settings

_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DECORATOR = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

def needs_manage_server():
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.manage_guild
    return app_commands.check(predicate)

# ---- Known keys & basic typing ----
KEYS_BOOL  = {"ENABLE_USGS", "ENABLE_RELIEFWEB", "ENABLE_EONET", "ENABLE_GDACS"}
KEYS_INT   = {"DISASTER_POLL_MINUTES", "RELIEFWEB_LIMIT", "DISASTER_CHANNEL_ID"}
KEYS_FLOAT = {"USGS_MIN_MAG", "USGS_PING_MAG"}
KEYS_FREE  = {
    "DISASTER_MODE",        # "rt" or "digest"
    "DIGEST_TIME_UTC",      # "HH:MM"
    "RELIEFWEB_APPNAME",
    "ALERT_ROLE_NAME",
    "DEXSCREENER_CHAIN",
}
ALL_KEYS = sorted(KEYS_BOOL | KEYS_INT | KEYS_FLOAT | KEYS_FREE)

def _coerce_value(key: str, value: str) -> str:
    k = key.upper()
    if k in KEYS_BOOL:
        s = value.strip().lower()
        if s in {"1","true","yes","y","on"}:  return "true"
        if s in {"0","false","no","n","off"}: return "false"
        raise ValueError("bool expected (true/false)")
    if k in KEYS_INT:
        int(value)  # will raise if invalid
        return str(int(value))
    if k in KEYS_FLOAT:
        float(value)  # will raise if invalid
        return str(float(value))
    return value  # free-form

class SettingsAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.store = Settings()

    async def cog_load(self):
        await self.store.init()

    # --- /settings_show ---
    @GUILD_DECORATOR
    @app_commands.command(name="settings_show", description="Show current live settings.")
    async def settings_show(self, interaction: discord.Interaction):
        keys = [
            # channels & mode
            "DISASTER_CHANNEL_ID",
            "DISASTER_MODE",
            "DIGEST_TIME_UTC",
            "DISASTER_POLL_MINUTES",
            # sources
            "ENABLE_USGS", "USGS_MIN_MAG", "USGS_PING_MAG",
            "ENABLE_RELIEFWEB", "RELIEFWEB_LIMIT", "RELIEFWEB_APPNAME",
            "ENABLE_EONET",
            "ENABLE_GDACS",
            # misc
            "ALERT_ROLE_NAME",
            "DEXSCREENER_CHAIN",
        ]
        lines = []
        for k in keys:
            fallback = os.getenv(k) or "—"
            v = await self.store.get(k, fallback)
            lines.append(f"**{k}**: {v}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # --- key autocomplete ---
    async def key_autocomplete(self, interaction: discord.Interaction, current: str):
        cur = (current or "").upper()
        return [
            app_commands.Choice(name=k, value=k)
            for k in ALL_KEYS
            if cur in k
        ][:25]

    # --- /settings_set ---
    @GUILD_DECORATOR
    @needs_manage_server()
    @app_commands.command(name="settings_set", description="Update a setting (Manage Server).")
    @app_commands.describe(key="Setting key", value="New value")
    @app_commands.autocomplete(key=key_autocomplete)
    async def settings_set(self, interaction: discord.Interaction, key: str, value: str):
        key_u = key.upper()
        if key_u not in ALL_KEYS:
            return await interaction.response.send_message(
                f"❌ Unknown key `{key}`. Try one of: {', '.join(ALL_KEYS)}",
                ephemeral=True
            )
        try:
            coerced = _coerce_value(key_u, value)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)

        await self.store.set(key_u, coerced)
        await interaction.response.send_message(f"✅ `{key_u}` set to `{coerced}`", ephemeral=True)

async def setup(bot):
    await bot.add_cog(SettingsAdmin(bot))
