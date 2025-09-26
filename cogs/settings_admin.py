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

class SettingsAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.store = Settings()

    async def cog_load(self):
        await self.store.init()

    @GUILD_DECORATOR
    @app_commands.command(name="settings_show", description="Show current live settings.")
    async def settings_show(self, interaction: discord.Interaction):
        keys = [
            "DISASTER_CHANNEL_ID",
            "DISASTER_MODE",
            "DISASTER_POLL_MINUTES",
            "USGS_MIN_MAG",
            "USGS_PING_MAG",
            "DIGEST_TIME_UTC",
            "ALERT_ROLE_NAME",
            "DEXSCREENER_CHAIN",
        ]
        lines = []
        for k in keys:
            fallback = os.getenv(k) or "—"
            v = await self.store.get(k, fallback)
            lines.append(f"**{k}**: {v}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @GUILD_DECORATOR
    @needs_manage_server()
    @app_commands.command(name="settings_set", description="Update a setting (Manage Server).")
    @app_commands.describe(key="Setting key", value="New value")
    async def settings_set(self, interaction: discord.Interaction, key: str, value: str):
        await self.store.set(key, value)
        await interaction.response.send_message(f"✅ `{key}` set to `{value}`", ephemeral=True)

async def setup(bot): 
    await bot.add_cog(SettingsAdmin(bot))
