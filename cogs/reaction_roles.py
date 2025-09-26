# cogs/reaction_roles.py
import os, aiosqlite
import discord
from discord.ext import commands
from discord import app_commands

_GUILD_ID = int(os.getenv("GUILD_ID") or 0) or None
GUILD_DEC = app_commands.guilds(_GUILD_ID) if _GUILD_ID else (lambda f: f)
DB = "pal_bot.sqlite"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS reaction_roles(
  message_id INTEGER NOT NULL,
  emoji      TEXT    NOT NULL,
  role_id    INTEGER NOT NULL,
  PRIMARY KEY(message_id, emoji)
);
"""

class ReactionRoles(commands.Cog):
    def __init__(self, bot): self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB) as db:
            await db.execute(CREATE_SQL)
            await db.commit()

    @GUILD_DEC
    @app_commands.command(name="rr_add", description="Bind an emoji to a role on a message.")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(message_id="Target message ID", emoji="Emoji", role="Role to grant")
    async def rr_add(self, inter: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
        async with aiosqlite.connect(DB) as db:
            await db.execute(
                "INSERT OR REPLACE INTO reaction_roles(message_id,emoji,role_id) VALUES(?,?,?)",
                (int(message_id), emoji, int(role.id))
            )
            await db.commit()
        await inter.response.send_message(f"✅ Bound `{emoji}` → **{role.name}** on `{message_id}`.", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="rr_remove", description="Unbind an emoji from a message.")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.describe(message_id="Target message ID", emoji="Emoji")
    async def rr_remove(self, inter: discord.Interaction, message_id: str, emoji: str):
        async with aiosqlite.connect(DB) as db:
            await db.execute("DELETE FROM reaction_roles WHERE message_id=? AND emoji=?",
                             (int(message_id), emoji))
            await db.commit()
        await inter.response.send_message("🗑️ Unbound.", ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id != (_GUILD_ID or payload.guild_id):  # allow if unset
            pass
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT role_id FROM reaction_roles WHERE message_id=? AND emoji=?",
                                   (payload.message_id, str(payload.emoji)))
            row = await cur.fetchone()
        if not row: return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return
        member = guild.get_member(payload.user_id)
        if not member or member.bot: return
        role = guild.get_role(row[0])
        if not role: return
        try:
            await member.add_roles(role, reason="Reaction role add")
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT role_id FROM reaction_roles WHERE message_id=? AND emoji=?",
                                   (payload.message_id, str(payload.emoji)))
            row = await cur.fetchone()
        if not row: return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return
        member = guild.get_member(payload.user_id)
        if not member or member.bot: return
        role = guild.get_role(row[0])
        if not role: return
        try:
            await member.remove_roles(role, reason="Reaction role remove")
        except discord.Forbidden:
            pass

async def setup(bot): await bot.add_cog(ReactionRoles(bot))
