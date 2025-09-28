# cogs/roles_setup.py
import os
import discord
from discord import app_commands
from discord.ext import commands

# Core roles we want to exist.
# You can edit this list or drive some via env if you like.
CORE_ROLES = [
    {"name": os.getenv("ALERT_ROLE_NAME", "Disaster Alerts"), "mentionable": True},
    {"name": os.getenv("RAID_ROLE_NAME", "Raiders"), "mentionable": True},

    # Verified professions (feel free to toggle mentionable)
    {"name": "Paramedic (Verified)", "mentionable": False},
    {"name": "Doctor (Verified)", "mentionable": False},
    {"name": "Nurse (Verified)", "mentionable": False},
    {"name": "EMT (Verified)", "mentionable": False},
    {"name": "Disaster Relief Pro", "mentionable": False},
    # Optional examples for future leveling rewards; comment out if not needed:
    # {"name": "Medic (Lvl 5)", "mentionable": False},
    # {"name": "Commander (Lvl 10)", "mentionable": False},
]

_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

class RolesSetup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Auto-run once the bot is ready (for all guilds the bot is in)
    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self.ensure_roles(guild)

    async def ensure_roles(self, guild: discord.Guild) -> list[str]:
        created: list[str] = []
        existing = {role.name: role for role in guild.roles}
        for spec in CORE_ROLES:
            name = spec["name"]
            if not name or name in existing:
                continue
            try:
                await guild.create_role(
                    name=name,
                    mentionable=spec.get("mentionable", False),
                    reason="Auto-created by pal_bot",
                )
                created.append(name)
            except discord.Forbidden:
                # Missing Manage Roles or role hierarchy
                pass
            except Exception:
                pass
        return created

    # ----- Slash commands -----
    @GUILD_DEC
    @app_commands.command(name="roles_bootstrap", description="Create any missing core roles (Disaster Alerts, etc.).")
    async def roles_bootstrap(self, inter: discord.Interaction):
        if not inter.user.guild_permissions.manage_roles and not inter.user.guild_permissions.manage_guild:
            return await inter.response.send_message("🚫 Need **Manage Roles** or **Manage Server**.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        created = await self.ensure_roles(inter.guild)
        if created:
            await inter.followup.send(f"✅ Created roles: {', '.join(created)}", ephemeral=True)
        else:
            await inter.followup.send("ℹ️ All core roles already exist.", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="roles_list", description="List server roles (top 50 by position).")
    async def roles_list(self, inter: discord.Interaction):
        roles = sorted(inter.guild.roles, key=lambda r: r.position, reverse=True)[:50]
        lines = [f"- {r.name} (ID: `{r.id}`)" for r in roles]
        e = discord.Embed(title="🧩 Roles (top by position)", description="\n".join(lines), color=discord.Color.blurple())
        await inter.response.send_message(embed=e, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(RolesSetup(bot))
