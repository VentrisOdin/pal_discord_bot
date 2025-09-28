import os
import discord
from discord.ext import commands
from discord import app_commands

_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @GUILD_DEC
    @app_commands.command(name="bot_help", description="Get help with bot commands") 
    async def help_command(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🤖 Palaemon Bot – Command Help",
            description="Here are all the available commands organized by category:",
            color=discord.Color.blue()
        )

        # Basic Commands
        embed.add_field(
            name="🌍 Disaster Tracking",
            value=(
                "`/disasters_now` – Fetch latest disaster alerts\n"
                "`/status` – Check disaster watcher status\n"
                "`/subscribe` – Get disaster alert notifications"
            ),
            inline=False
        )

        # Market Commands
        embed.add_field(
            name="💰 Market & Price",
            value=(
                "`/price` – Check PAL or any token price\n"
                "`/price_debug` – Show detailed price info"
            ),
            inline=False
        )

        # Leveling & XP
        embed.add_field(
            name="🏆 Leveling & XP",
            value=(
                "`/daily` – Claim daily XP bonus (streaks!)\n"
                "`/rank` – Check your level progress\n"
                "`/top` – View server leaderboard\n"
                "`/titles` – See available rank titles\n"
                "`/level_curve` – View XP requirements"
            ),
            inline=False
        )

        # Social & Engagement
        embed.add_field(
            name="🎉 Social & Raids",
            value=(
                "`/raid_new` – Start a social media raid\n"
                "`/raid_status` – Check active raids\n"
                "`/poll` – Create a poll\n"
                "`/profile` – View your profile & roles"
            ),
            inline=False
        )

        # Utility
        embed.add_field(
            name="🔧 Utility",
            value=(
                "`/guide` – Bot usage guide (DM)\n"
                "`/ping` – Check bot response time\n"
                "`/uptime` – Bot uptime info"
            ),
            inline=False
        )

        # Admin Commands (if user has permissions)
        if interaction.user.guild_permissions.manage_guild:
            embed.add_field(
                name="🛠️ Admin Commands",
                value=(
                    "`/announce` – Post announcements\n"
                    "`/admin_guide` – Full admin guide (DM)\n"
                    "`/roles_bootstrap` – Create server roles\n"
                    "`/level_givexp` – Give XP to users\n"
                    "`/debug` – View bot configuration\n"
                    "`/verify_queue` – Manage verification requests"
                ),
                inline=False
            )

        embed.set_footer(text="Use /guide for detailed instructions • Powered by $PAL")
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Help(bot))
