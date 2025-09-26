import discord
from discord.ext import commands
from discord import app_commands

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show available bot commands, grouped by category.")
    async def help(self, inter: discord.Interaction):
        embed = discord.Embed(
            title="🤖 Bot Commands",
            description="Here are the commands you can use:",
            color=discord.Color.blue()
        )

        for cog_name, cog in self.bot.cogs.items():
            cmds = [c for c in self.bot.tree.get_commands(guild=inter.guild) if c.module.endswith(cog_name.lower())]
            if not cmds:
                continue
            lines = [f"/{c.name} — {c.description}" for c in cmds]
            embed.add_field(name=cog_name, value="\n".join(lines), inline=False)

        await inter.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Help(bot))
