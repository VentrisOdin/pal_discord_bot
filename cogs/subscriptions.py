import discord
from discord.ext import commands
from discord import app_commands

# Define safe roles here — only these can be self-assigned
SUBSCRIBE_ROLES = {
    "disasters": "Disaster Alerts",
    "market": "Market Watch",
    "announcements": "Announcements"
}

class Subscriptions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="subscribe", description="Subscribe to updates (e.g., disasters, market, announcements).")
    @app_commands.describe(category="Which category to subscribe to (disasters, market, announcements)")
    async def subscribe(self, inter: discord.Interaction, category: str):
        category = category.lower()
        if category not in SUBSCRIBE_ROLES:
            return await inter.response.send_message(
                f"❌ Unknown category. Options: {', '.join(SUBSCRIBE_ROLES)}",
                ephemeral=True
            )

        role_name = SUBSCRIBE_ROLES[category]
        role = discord.utils.get(inter.guild.roles, name=role_name)
        if not role:
            return await inter.response.send_message(
                f"⚠️ Role `{role_name}` not found. Ask an admin to create it.",
                ephemeral=True
            )

        if role in inter.user.roles:
            return await inter.response.send_message(
                f"ℹ️ You already have **{role_name}**.",
                ephemeral=True
            )

        await inter.user.add_roles(role)
        await inter.response.send_message(
            f"✅ You’re now subscribed to **{role_name}** updates!",
            ephemeral=False
        )

    @app_commands.command(name="unsubscribe", description="Unsubscribe from updates.")
    @app_commands.describe(category="Which category to unsubscribe from (disasters, market, announcements)")
    async def unsubscribe(self, inter: discord.Interaction, category: str):
        category = category.lower()
        if category not in SUBSCRIBE_ROLES:
            return await inter.response.send_message(
                f"❌ Unknown category. Options: {', '.join(SUBSCRIBE_ROLES)}",
                ephemeral=True
            )

        role_name = SUBSCRIBE_ROLES[category]
        role = discord.utils.get(inter.guild.roles, name=role_name)
        if not role:
            return await inter.response.send_message(
                f"⚠️ Role `{role_name}` not found. Ask an admin to create it.",
                ephemeral=True
            )

        if role not in inter.user.roles:
            return await inter.response.send_message(
                f"ℹ️ You don’t currently have **{role_name}**.",
                ephemeral=True
            )

        await inter.user.remove_roles(role)
        await inter.response.send_message(
            f"👋 You’ve unsubscribed from **{role_name}**.",
            ephemeral=False
        )

async def setup(bot):
    await bot.add_cog(Subscriptions(bot))
