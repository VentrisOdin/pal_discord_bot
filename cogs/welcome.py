import random
import discord
from discord.ext import commands

WELCOME_MESSAGES = [
    "👋 Welcome, {member.mention}! You just joined the lifeboat crew 🚑⛑️",
    "⚡ Another hero arrives: {member.mention}! Ready to save the world?",
    "🌍 Disaster relief just got stronger — {member.mention} has joined us!",
    "🚀 Glad to have you aboard, {member.mention}! Let’s build something great.",
    "🔥 Welcome {member.mention}, the mission just got even stronger!"
]

class Welcome(commands.Cog):
    def __init__(self, bot): 
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Post in general channel (set this in settings or hardcode channel ID)
        general = discord.utils.get(member.guild.text_channels, name="general")
        if general:
            msg = random.choice(WELCOME_MESSAGES).format(member=member)
            await general.send(msg)

        # DM the user
        try:
            await member.send(
                "👋 Welcome to **Palaemon Emergency Services!**\n\n"
                "🌍 Website: https://palaemon.vercel.app\n"
                "💰 How to Buy $PAL: https://palaemon.vercel.app/pal/how-to-buy\n"
                "📜 Please read the server rules and enjoy your stay!"
            )
        except:
            pass

async def setup(bot):
    await bot.add_cog(Welcome(bot))
