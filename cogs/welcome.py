# cogs/welcome.py
import random
import discord
from discord.ext import commands
from discord import app_commands

WELCOME_MESSAGES = [
    "👋 Welcome, {member.mention}! You just joined the lifeboat crew 🚑⛑️",
    "⚡ Another hero arrives: {member.mention}! Ready to save the world?",
    "🌍 Disaster relief just got stronger — {member.mention} has joined us!",
    "🚀 Glad to have you aboard, {member.mention}! Let’s build something great.",
    "🔥 Welcome {member.mention}, the mission just got even stronger!"
]

class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Rotate a text welcome (keeps it fun + dynamic)
        msg = random.choice(WELCOME_MESSAGES).format(member=member)

        # Send in general (if it exists)
        general = discord.utils.get(member.guild.text_channels, name="general")
        if general:
            await general.send(msg)

            # Fancy embed with buttons
            embed = discord.Embed(
                title="🚑 Welcome to Palaemon Emergency Services!",
                description=(
                    "We’re glad to have you, {0.mention}!\n\n"
                    "Here are some key resources to get started 👇"
                ).format(member),
                color=discord.Color.green(),
            )
            embed.set_footer(text="Powered by $PAL")

            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="🌍 Website", url="https://palaemon.vercel.app"))
            view.add_item(discord.ui.Button(label="📖 Whitepaper", url="https://palaemon.vercel.app/pal/whitepaper"))
            view.add_item(discord.ui.Button(label="💰 How to Buy $PAL", url="https://palaemon.vercel.app/pal/how-to-buy"))

            await general.send(embed=embed, view=view)

        # DM the new user (fails silently if DMs are closed)
        try:
            dm_embed = discord.Embed(
                title="👋 Welcome to Palaemon!",
                description=(
                    "Thanks for joining **Palaemon Emergency Services**!\n\n"
                    "🌍 [Visit our website](https://palaemon.vercel.app)\n"
                    "💰 [How to Buy $PAL](https://palaemon.vercel.app/pal/how-to-buy)\n"
                    "📜 Please read the rules and introduce yourself in #general!"
                ),
                color=discord.Color.blue(),
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
