import discord
from discord import app_commands
from discord.ext import commands
import time

class Utilities(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()

    @app_commands.command(description="Show bot uptime.")
    async def uptime(self, interaction: discord.Interaction):
        elapsed = int(time.time() - self.start_time)
        hours, rem = divmod(elapsed, 3600)
        minutes, seconds = divmod(rem, 60)
        await interaction.response.send_message(
            f"⏱️ Uptime: {hours}h {minutes}m {seconds}s", ephemeral=True
        )

    @app_commands.command(description="Show server member count.")
    async def members(self, interaction: discord.Interaction):
        count = interaction.guild.member_count
        await interaction.response.send_message(f"👥 Members: {count}")

    @app_commands.command(description="Count members in a role.")
    async def rolecount(self, interaction: discord.Interaction, role: discord.Role):
        count = len(role.members)
        await interaction.response.send_message(
            f"📊 {count} members have the role {role.name}."
        )

async def setup(bot):
    await bot.add_cog(Utilities(bot))
