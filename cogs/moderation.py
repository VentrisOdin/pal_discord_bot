import os
import discord
from discord.ext import commands
from discord import app_commands

_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DECORATOR = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

def needs_manage(perms_attr: str, label: str):
    async def predicate(inter: discord.Interaction):
        if not getattr(inter.user.guild_permissions, perms_attr, False):
            await inter.response.send_message(f"🚫 You need **{label}** permission.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------- Helpers ----------
    def _can_manage_role(self, guild: discord.Guild, role: discord.Role) -> tuple[bool, str | None]:
        me = guild.me
        if not me.guild_permissions.manage_roles:
            return False, "Bot lacks **Manage Roles** permission."
        if role >= me.top_role:
            return False, f"Role **{role.name}** is higher/equal to my top role. Move my bot role above it."
        return True, None

    # ---------- Role management ----------
    @GUILD_DECORATOR
    @app_commands.command(name="role_add", description="Assign a role to a member.")
    @app_commands.describe(member="Member to give the role to", role="Role to assign")
    @needs_manage("manage_roles", "Manage Roles")
    async def role_add(self, inter: discord.Interaction, member: discord.Member, role: discord.Role):
        ok, msg = self._can_manage_role(inter.guild, role)
        if not ok:
            return await inter.response.send_message(f"🚫 {msg}", ephemeral=True)
        if role in member.roles:
            return await inter.response.send_message(f"ℹ️ {member.mention} already has **{role.name}**.", ephemeral=True)

        await member.add_roles(role, reason=f"Assigned by {inter.user}")
        await inter.response.send_message(f"✅ Added **{role.name}** to {member.mention}.")

    @GUILD_DECORATOR
    @app_commands.command(name="role_remove", description="Remove a role from a member.")
    @app_commands.describe(member="Member to remove the role from", role="Role to remove")
    @needs_manage("manage_roles", "Manage Roles")
    async def role_remove(self, inter: discord.Interaction, member: discord.Member, role: discord.Role):
        ok, msg = self._can_manage_role(inter.guild, role)
        if not ok:
            return await inter.response.send_message(f"🚫 {msg}", ephemeral=True)
        if role not in member.roles:
            return await inter.response.send_message(f"ℹ️ {member.mention} doesn’t have **{role.name}**.", ephemeral=True)

        await member.remove_roles(role, reason=f"Removed by {inter.user}")
        await inter.response.send_message(f"✅ Removed **{role.name}** from {member.mention}.")

    @GUILD_DECORATOR
    @app_commands.command(name="role_create", description="Create a new role (optional: mentionable).")
    @app_commands.describe(name="Role name", mentionable="Whether the role is mentionable")
    @needs_manage("manage_roles", "Manage Roles")
    async def role_create(self, inter: discord.Interaction, name: str, mentionable: bool = False):
        if not inter.guild.me.guild_permissions.manage_roles:
            return await inter.response.send_message("🚫 Bot lacks **Manage Roles**.", ephemeral=True)

        role = await inter.guild.create_role(name=name, mentionable=mentionable, reason=f"Created by {inter.user}")
        await inter.response.send_message(f"✅ Created role **{role.name}** (ID: `{role.id}`).\n"
                                          f"Tip: Move my bot role **above** it if I should assign it.")

    @GUILD_DECORATOR
    @app_commands.command(name="role_delete", description="Delete a role.")
    @app_commands.describe(role="Role to delete")
    @needs_manage("manage_roles", "Manage Roles")
    async def role_delete(self, inter: discord.Interaction, role: discord.Role):
        ok, msg = self._can_manage_role(inter.guild, role)
        if not ok:
            return await inter.response.send_message(f"🚫 {msg}", ephemeral=True)

        name = role.name
        await role.delete(reason=f"Deleted by {inter.user}")
        await inter.response.send_message(f"🗑️ Deleted role **{name}**.")

    # ---------- Other moderation you already had (keep if you want) ----------
    @GUILD_DECORATOR
    @app_commands.command(description="Purge last N messages.")
    @needs_manage("manage_messages", "Manage Messages")
    async def purge(self, inter: discord.Interaction, amount: int):
        deleted = await inter.channel.purge(limit=amount)
        try:
            await inter.response.send_message(f"🧹 Deleted {len(deleted)} messages.", ephemeral=True)
        except discord.InteractionResponded:
            pass

    @GUILD_DECORATOR
    @app_commands.command(description="Kick a member.")
    @needs_manage("kick_members", "Kick Members")
    async def kick(self, inter: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        await member.kick(reason=reason)
        await inter.response.send_message(f"👢 Kicked {member.mention} — {reason}")

    @GUILD_DECORATOR
    @app_commands.command(description="Ban a member.")
    @needs_manage("ban_members", "Ban Members")
    async def ban(self, inter: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        await member.ban(reason=reason)
        await inter.response.send_message(f"🔨 Banned {member.mention} — {reason}")

    @GUILD_DECORATOR
    @app_commands.command(description="Set channel slowmode (seconds).")
    @needs_manage("manage_channels", "Manage Channels")
    async def slowmode(self, inter: discord.Interaction, seconds: int):
        await inter.channel.edit(slowmode_delay=seconds)
        await inter.response.send_message(f"🐢 Slowmode set to {seconds}s.")

async def setup(bot):
    await bot.add_cog(Moderation(bot))
