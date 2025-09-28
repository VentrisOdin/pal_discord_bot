# cogs/verify.py
import os
import aiosqlite
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

DB_PATH = os.getenv("DB_PATH", "pal_bot.sqlite")
REVIEW_CH_ID = int(os.getenv("VERIFY_REVIEW_CHANNEL_ID", "0") or 0)

# Verified role allowlist (names must match your server roles)
DEFAULT_VERIFIED = [
    "Paramedic (Verified)",
    "Doctor (Verified)",
    "Nurse (Verified)",
    "EMT (Verified)",
    "Disaster Relief Pro",
]

def allowlist() -> set[str]:
    env = (os.getenv("VERIFIED_ROLES") or "").strip()
    if env:
        return {x.strip() for x in env.split(",") if x.strip()}
    return set(DEFAULT_VERIFIED)

# Helpers
def admin_or_mod(inter: discord.Interaction) -> bool:
    perms = inter.user.guild_permissions
    return perms.manage_guild or perms.manage_roles or perms.administrator

class Verify(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- DB ----------
    async def _db(self):
        db = await aiosqlite.connect(DB_PATH)
        await db.execute("""
          CREATE TABLE IF NOT EXISTS verify_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id  INTEGER NOT NULL,
            role_name TEXT NOT NULL,
            note TEXT,
            attachment_url TEXT,
            status TEXT NOT NULL DEFAULT 'pending',  -- pending/approved/denied
            reviewer_id INTEGER,
            ts INTEGER NOT NULL
          )
        """)
        await db.commit()
        return db

    # ---------- Slash: user submits request ----------
    @app_commands.command(name="verify", description="Request a verified professional role.")
    @app_commands.describe(role="Choose a profession to verify (e.g., Paramedic (Verified))",
                           note="Optional context (e.g., license/registration info)",
                           evidence="Optional file; reviewed privately by staff")
    async def verify(self, inter: discord.Interaction,
                     role: str,
                     note: Optional[str] = None,
                     evidence: Optional[discord.Attachment] = None):
        roleset = allowlist()
        if role not in roleset:
            return await inter.response.send_message(
                f"Please choose one of: {', '.join(sorted(roleset))}", ephemeral=True
            )

        await inter.response.defer(ephemeral=True, thinking=True)
        attach_url = None
        if evidence and evidence.size <= 15 * 1024 * 1024:  # 15MB guard
            # Don’t download; just store the CDN link for reviewers
            attach_url = evidence.url

        import time
        async with await self._db() as db:
            await db.execute(
              "INSERT INTO verify_requests(guild_id, user_id, role_name, note, attachment_url, ts) VALUES(?,?,?,?,?,?)",
              (inter.guild_id, inter.user.id, role, note or "", attach_url, int(time.time()))
            )
            await db.commit()

        # Notify user
        await inter.followup.send("✅ Your verification request has been submitted. Our moderators will review it soon.",
                                  ephemeral=True)

        # Notify reviewer channel if configured
        if REVIEW_CH_ID:
            ch = inter.guild.get_channel(REVIEW_CH_ID)  # type: ignore
            if isinstance(ch, discord.TextChannel):
                e = discord.Embed(title="🩺 New Verification Request", color=discord.Color.blurple())
                e.add_field(name="User", value=f"{inter.user.mention} (`{inter.user.id}`)", inline=False)
                e.add_field(name="Requested Role", value=role, inline=True)
                e.add_field(name="Note", value=note or "—", inline=False)
                if attach_url:
                    e.add_field(name="Evidence", value=attach_url, inline=False)
                await ch.send(embed=e)

    # ---------- Slash: reviewers list pending ----------
    @app_commands.command(name="verify_queue", description="(Staff) List pending verification requests.")
    async def verify_queue(self, inter: discord.Interaction):
        if not admin_or_mod(inter):
            return await inter.response.send_message("🚫 Staff only.", ephemeral=True)
        await inter.response.defer(ephemeral=True)

        async with await self._db() as db:
            cur = await db.execute(
                "SELECT id, user_id, role_name, note FROM verify_requests WHERE guild_id=? AND status='pending' ORDER BY id ASC LIMIT 20",
                (inter.guild_id,)
            )
            rows = await cur.fetchall()

        if not rows:
            return await inter.followup.send("No pending requests.", ephemeral=True)

        lines = []
        for rid, uid, role_name, note in rows:
            member = inter.guild.get_member(uid)  # type: ignore
            who = member.mention if member else f"`{uid}`"
            lines.append(f"• `#{rid}` {who} → **{role_name}** — {note or '—'}")
        await inter.followup.send("\n".join(lines), ephemeral=True)

    # ---------- Slash: approve ----------
    @app_commands.command(name="verify_approve", description="(Staff) Approve and assign a verified role.")
    @app_commands.describe(request_id="ID from /verify_queue")
    async def verify_approve(self, inter: discord.Interaction, request_id: int):
        if not admin_or_mod(inter):
            return await inter.response.send_message("🚫 Staff only.", ephemeral=True)
        await inter.response.defer(ephemeral=True)

        async with await self._db() as db:
            cur = await db.execute(
              "SELECT user_id, role_name FROM verify_requests WHERE id=? AND guild_id=? AND status='pending'",
              (request_id, inter.guild_id)
            )
            row = await cur.fetchone()
            if not row:
                return await inter.followup.send("Request not found or already processed.", ephemeral=True)
            user_id, role_name = row

            # Assign role
            member = inter.guild.get_member(user_id)  # type: ignore
            if not member:
                return await inter.followup.send("User not found in this server.", ephemeral=True)
            role_obj = discord.utils.get(inter.guild.roles, name=role_name)  # type: ignore
            if not role_obj:
                return await inter.followup.send(f"Role **{role_name}** does not exist. Create it first.", ephemeral=True)

            me = inter.guild.me  # type: ignore
            if not me.guild_permissions.manage_roles or role_obj >= me.top_role:
                return await inter.followup.send("I can’t manage that role. Move my role higher.", ephemeral=True)

            await member.add_roles(role_obj, reason=f"Verified by {inter.user}")
            await db.execute("UPDATE verify_requests SET status='approved', reviewer_id=? WHERE id=?",
                             (inter.user.id, request_id))
            await db.commit()

        # DM user
        try:
            await member.send(f"✅ Your verification was approved. You’ve been given **{role_name}** in **{inter.guild.name}**.")  # type: ignore
        except Exception:
            pass

        await inter.followup.send(f"✅ Approved and assigned **{role_name}** to {member.mention}.", ephemeral=True)

    # ---------- Slash: deny ----------
    @app_commands.command(name="verify_deny", description="(Staff) Deny a verification request.")
    @app_commands.describe(request_id="ID from /verify_queue", reason="Optional reason")
    async def verify_deny(self, inter: discord.Interaction, request_id: int, reason: Optional[str] = None):
        if not admin_or_mod(inter):
            return await inter.response.send_message("🚫 Staff only.", ephemeral=True)
        await inter.response.defer(ephemeral=True)

        async with await self._db() as db:
            cur = await db.execute(
              "SELECT user_id, role_name FROM verify_requests WHERE id=? AND guild_id=? AND status='pending'",
              (request_id, inter.guild_id)
            )
            row = await cur.fetchone()
            if not row:
                return await inter.followup.send("Request not found or already processed.", ephemeral=True)
            user_id, role_name = row
            await db.execute("UPDATE verify_requests SET status='denied', reviewer_id=? WHERE id=?",
                             (inter.user.id, request_id))
            await db.commit()

        member = inter.guild.get_member(user_id)  # type: ignore
        try:
            if member:
                await member.send(f"❌ Your verification for **{role_name}** was denied. Reason: {reason or '—'}")
        except Exception:
            pass

        await inter.followup.send("🚫 Request denied.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Verify(bot))
