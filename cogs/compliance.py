import discord
from discord.ext import commands
from discord import app_commands
from services.user_prefs import UserPrefs
import os

class Compliance(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.user_prefs = UserPrefs()

    async def cog_load(self):
        await self.user_prefs.init()

    @app_commands.command(name="about", description="Learn about this bot and its features")
    async def about(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🤖 About Palaemon Bot", 
            description="Your comprehensive community assistant for the Palaemon ecosystem.",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="🌍 Disaster Monitoring", 
            value="Real-time alerts from 12+ global sources:\n• USGS Earthquakes\n• NASA EONET Events\n• NHC Hurricane Advisories\n• Tsunami Warnings (PTWC)\n• WHO Health Emergencies\n• And more...",
            inline=False
        )
        
        embed.add_field(
            name="📊 Token Features",
            value="• PAL token price tracking\n• Market alerts & notifications\n• Price change monitoring",
            inline=True
        )
        
        embed.add_field(
            name="🎮 Community Features", 
            value="• XP & Leveling system\n• Recruitment rewards\n• Daily platypus posts\n• Raid coordination",
            inline=True
        )
        
        embed.add_field(
            name="🔗 Links",
            value="[Palaemon Website](https://palaemon.vercel.app)\n[GitHub](https://github.com/palaemon-labs)\n[Privacy Policy](/privacy)",
            inline=False
        )
        
        embed.set_footer(text="Built with ❤️ for the Palaemon community")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="privacy", description="View our privacy policy and data usage")
    async def privacy(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🛡️ Privacy Policy", 
            description="Transparency about what data we collect and how we use it.",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="📝 Data We Collect",
            value="• **User IDs**: For XP tracking and referrals\n• **Message counts**: For leveling system\n• **Join dates**: For welcome messages\n• **Referral codes**: For recruitment rewards\n• **Settings**: User preferences (DM opt-out, etc.)",
            inline=False
        )
        
        embed.add_field(
            name="🎯 How We Use Data", 
            value="• Track XP and community engagement\n• Send welcome messages and notifications\n• Provide personalized features\n• Monitor disaster alerts and token prices",
            inline=False
        )
        
        embed.add_field(
            name="🚫 What We DON'T Do",
            value="• Sell your data to third parties\n• Store message content\n• Share personal info outside Discord\n• Track you outside this server",
            inline=False
        )
        
        embed.add_field(
            name="⚙️ Your Control",
            value="• `/optout_dm` - Stop DM notifications\n• `/optin_dm` - Re-enable DM notifications\n• `/contact_staff` - Request data deletion\n• Leave the server - All data is automatically removed",
            inline=False
        )
        
        embed.add_field(
            name="🔒 Data Security",
            value="• Encrypted database storage\n• No third-party analytics\n• Regular security updates\n• Open source code available",
            inline=False
        )
        
        embed.set_footer(text="Last updated: October 2025 • Contact staff for questions")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="optout_dm", description="Stop receiving DM notifications from the bot")
    async def optout_dm(self, interaction: discord.Interaction):
        await self.user_prefs.set_dm_opt_out(interaction.user.id, interaction.guild_id, True)
        
        embed = discord.Embed(
            title="✅ DM Notifications Disabled",
            description="You will no longer receive DM notifications from this bot.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="What's affected:",
            value="• Welcome messages\n• Level-up notifications\n• Recruitment rewards\n• Price alerts (if enabled)",
            inline=False
        )
        embed.add_field(
            name="Re-enable anytime:",
            value="Use `/optin_dm` to turn notifications back on.",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="optin_dm", description="Resume receiving DM notifications from the bot")
    async def optin_dm(self, interaction: discord.Interaction):
        await self.user_prefs.set_dm_opt_out(interaction.user.id, interaction.guild_id, False)
        
        embed = discord.Embed(
            title="✅ DM Notifications Enabled", 
            description="You will now receive DM notifications from this bot.",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="You'll receive:",
            value="• Welcome messages\n• Level-up notifications\n• Recruitment rewards\n• Price alerts (if configured)",
            inline=False
        )
        embed.add_field(
            name="Opt-out anytime:",
            value="Use `/optout_dm` to disable notifications.",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="contact_staff", description="Send a message to the server staff")
    @app_commands.describe(message="Your message to the staff team")
    async def contact_staff(self, interaction: discord.Interaction, message: str):
        # Get staff channel (use your existing mod/review channel)
        STAFF_CHANNEL_ID = int(os.getenv("VERIFY_REVIEW_CHANNEL_ID", "1421763495304630354"))
        staff_channel = self.bot.get_channel(STAFF_CHANNEL_ID)
        
        if not staff_channel:
            await interaction.response.send_message(
                "❌ Unable to contact staff at this time. Please try again later.",
                ephemeral=True
            )
            return
        
        # Create staff notification embed
        embed = discord.Embed(
            title="📨 Staff Contact Request",
            description=message,
            color=discord.Color.orange(),
            timestamp=interaction.created_at
        )
        embed.set_author(
            name=f"{interaction.user.display_name} ({interaction.user})",
            icon_url=interaction.user.display_avatar.url
        )
        embed.add_field(name="User ID", value=interaction.user.id, inline=True)
        embed.add_field(name="Channel", value=interaction.channel.mention, inline=True)
        
        try:
            await staff_channel.send(embed=embed)
            
            # Confirm to user
            await interaction.response.send_message(
                "✅ **Message sent to staff!**\n\nA staff member will review your message and respond if needed. Thank you for reaching out!",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                "❌ Failed to send message to staff. Please try contacting a moderator directly.",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(Compliance(bot))