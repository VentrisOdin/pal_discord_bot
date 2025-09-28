# cogs/admin.py
import os
import discord
from discord import app_commands
from discord.ext import commands

# Add guild scoping
_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

def make_embed(title: str, desc: str, color=discord.Color.blurple()):
    return discord.Embed(title=title, description=desc, color=color)

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- Announce ----------
    @GUILD_DEC  # Add this decorator
    @app_commands.command(description="Post an announcement in the current channel (Manage Server only).")
    @app_commands.describe(message="Your announcement text")
    async def announce(self, interaction: discord.Interaction, message: str):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                "🚫 You need **Manage Server** permission.", ephemeral=True
            )
        embed = make_embed("📣 Announcement", message, color=discord.Color.gold())
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ Announcement posted.", ephemeral=True)

    # ---------- Debug ----------
    @GUILD_DEC  # Add this decorator
    @app_commands.command(description="Show live bot config values (ephemeral).")
    async def debug(self, interaction: discord.Interaction):
        fields = [
            ("Guild ID", os.getenv("GUILD_ID") or "—"),
            ("Disaster Channel ID", os.getenv("DISASTER_CHANNEL_ID") or "—"),
            ("Mode", os.getenv("DISASTER_MODE") or "rt"),
            ("Poll (min)", os.getenv("DISASTER_POLL_MINUTES") or "5"),
            ("USGS Min Mag", os.getenv("USGS_MIN_MAG") or "6.0"),
            ("ReliefWeb Limit", os.getenv("RELIEFWEB_LIMIT") or "5"),
            ("ReliefWeb App", os.getenv("RELIEFWEB_APPNAME") or "—"),
            ("Digest Time (UTC)", os.getenv("DIGEST_TIME_UTC") or "—"),
            ("PAL Token", os.getenv("PAL_TOKEN_ADDRESS") or "—"),
            ("Dex Chain", os.getenv("DEXSCREENER_CHAIN") or "—"),
        ]
        e = discord.Embed(title="🔧 Bot Debug", color=discord.Color.greyple())
        for name, value in fields:
            e.add_field(name=name, value=value, inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ---------- IDs ----------
    @GUILD_DEC  # Add this decorator
    @app_commands.command(description="Show current server and channel IDs (ephemeral).")
    async def ids(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id or "—"
        channel_id = interaction.channel_id or "—"
        e = discord.Embed(title="🆔 IDs", color=discord.Color.teal())
        e.add_field(name="Guild ID", value=guild_id, inline=True)
        e.add_field(name="Channel ID", value=channel_id, inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ---------- Help ----------
    @GUILD_DEC  # Add this decorator
    @app_commands.command(description="Show bot help categories.")
    async def help(self, interaction: discord.Interaction):
        e = discord.Embed(
            title="🤖 Palaemon Bot – Help",
            description="Here are the main categories of commands. Use `/` and start typing to see available commands.",
            color=discord.Color.blurple(),
        )
        e.add_field(
            name="🌍 Disasters",
            value="`/disasters_now` – Force fetch alerts\n(Daily digest goes to #general automatically)",
            inline=False,
        )
        e.add_field(
            name="📊 Market",
            value="`/price` – Show PAL or other token price\n`/price_debug` – Show raw pair info",
            inline=False,
        )
        e.add_field(
            name="👮 Moderation",
            value="`/role_add` `/role_remove` `/purge` `/kick` `/ban` `/slowmode`",
            inline=False,
        )
        e.add_field(
            name="📢 Admin",
            value="`/announce` – Post announcements\n`/debug` – Show config\n`/ids` – Show IDs",
            inline=False,
        )
        e.add_field(
            name="🎉 Engagement",
            value="`/poll` `/raid_new` `/raid_status` `/raid_ping` `/raid_end`\nMore features coming soon (leveling, trivia, QOTD).",
            inline=False,
        )
        e.set_footer(text="Powered by $PAL – Palaemon Emergency Services")
        await interaction.response.send_message(embed=e, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
