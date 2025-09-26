import os
import discord
from discord import app_commands
from discord.ext import commands

_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DECORATOR = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

def ok_embed(title: str, desc: str):
    return discord.Embed(title=title, description=desc)

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---- Admin broadcast ----
    @GUILD_DECORATOR
    @app_commands.command(description="Post an announcement here (Manage Server only).")
    @app_commands.describe(message="Your announcement text")
    async def announce(self, interaction: discord.Interaction, message: str):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                "You need **Manage Server** permission.", ephemeral=True
            )
        await interaction.channel.send(embed=ok_embed("📣 Announcement", message))
        await interaction.response.send_message("Posted.", ephemeral=True)

    # ---- Debug / IDs ----
    @GUILD_DECORATOR
    @app_commands.command(description="Show live bot config (ephemeral).")
    async def debug(self, interaction: discord.Interaction):
        fields = [
            ("Guild ID", os.getenv("GUILD_ID") or "—"),
            ("Disaster Channel ID", os.getenv("DISASTER_CHANNEL_ID") or "—"),
            ("Mode", os.getenv("DISASTER_MODE") or "rt"),
            ("Poll (min)", os.getenv("DISASTER_POLL_MINUTES") or "5"),
            ("USGS Min Mag", os.getenv("USGS_MIN_MAG") or "6.0"),
            ("Digest Time UTC", os.getenv("DIGEST_TIME_UTC") or "09:00"),
            ("ReliefWeb Limit", os.getenv("RELIEFWEB_LIMIT") or "5"),
            ("ReliefWeb App", os.getenv("RELIEFWEB_APPNAME") or "—"),
            ("Dex chain", os.getenv("DEXSCREENER_CHAIN") or "—"),
        ]
        e = discord.Embed(title="🔧 Bot Debug")
        for name, value in fields:
            e.add_field(name=name, value=value, inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @GUILD_DECORATOR
    @app_commands.command(description="Show this server and channel IDs (ephemeral).")
    async def ids(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"Guild: `{interaction.guild_id}`\nChannel: `{interaction.channel_id}`",
            ephemeral=True,
        )

    # ---- Help ----
    @GUILD_DECORATOR
    @app_commands.command(name="help", description="Show commands & tips.")
    async def help_cmd(self, interaction: discord.Interaction):
        text = (
            "**Disasters**\n"
            "• `/disasters_now` — Fetch & post latest now\n"
            "• `/status` — Uptime, last poll, next digest\n\n"
            "**Admin**\n"
            "• `/announce <message>` — Post an announcement\n"
            "• `/debug` `/ids` — Config & IDs (ephemeral)\n"
            "• `/settings_show` — View live settings\n"
            "• `/settings_set key:<K> value:<V>` — Update setting (Manage Server)\n\n"
            "**Market**\n"
            "• `/price [query]` — Token price (0x address or text)\n"
            "• `/price_debug [query]` — List candidate pairs (ephemeral)\n\n"
            "Tips: Create role **Disaster Alerts** for severe-event pings; use `/settings_set` "
            "to tweak thresholds without editing files."
        )
        await interaction.response.send_message(text, ephemeral=True)

    # ---- Friendly app command error handling ----
    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            return await interaction.response.send_message("You lack permissions for that.", ephemeral=True)
        if isinstance(error, app_commands.CommandOnCooldown):
            return await interaction.response.send_message("⏳ Easy there—try again shortly.", ephemeral=True)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Oops, something went wrong.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Oops, something went wrong.", ephemeral=True)
        except Exception:
            pass  # keep calm

async def setup(bot):
    await bot.add_cog(Admin(bot))
