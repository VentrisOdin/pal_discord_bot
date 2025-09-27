# cogs/leveling.py
import os
import time
import math
import random
import aiosqlite
from typing import Dict, Tuple, List

import discord
from discord import app_commands
from discord.ext import commands

DB_PATH = os.getenv("DB_PATH", "pal_bot.sqlite")
LEVEL_ANNOUNCE = (os.getenv("LEVEL_ANNOUNCE", "true").strip().lower() in {"1", "true", "yes", "y", "on"})
AWARD_COOLDOWN = int(os.getenv("LEVEL_COOLDOWN_SEC", "60") or 60)  # per-user cooldown for XP
AWARD_MIN = int(os.getenv("LEVEL_XP_MIN", "15") or 15)
AWARD_MAX = int(os.getenv("LEVEL_XP_MAX", "25") or 25)

# Optional role rewards: LEVEL_ROLE_5=Medic, LEVEL_ROLE_10=Field Commander, ...
def _load_level_roles_from_env() -> Dict[int, str]:
    mapping: Dict[int, str] = {}
    for k, v in os.environ.items():
        if k.startswith("LEVEL_ROLE_"):
            try:
                lvl = int(k.split("_")[-1])
                name = v.strip()
                if lvl > 0 and name:
                    mapping[lvl] = name
            except Exception:
                continue
    return mapping

LEVEL_ROLE_NAMES = _load_level_roles_from_env()

# Optional guild scoping for fast slash sync
_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

# ----- Level formula (simple & transparent) -----
# 1 level per 100 XP (customizable if desired)
def level_from_xp(xp: int) -> int:
    return max(1, (xp // 100) + 1)

def progress_to_next(xp: int) -> Tuple[int, int, int]:
    """
    Returns: (level, xp_in_level, xp_required_for_next)
    """
    lvl = level_from_xp(xp)
    base = (lvl - 1) * 100
    nxt = lvl * 100
    return lvl, xp - base, nxt - base

def progress_bar(xp_in: int, xp_req: int, width: int = 12) -> str:
    fill = int((xp_in / max(1, xp_req)) * width)
    return "█" * fill + "░" * (width - fill)

class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # local in-memory cooldown: { (guild_id, user_id): last_ts }
        self._cooldown: Dict[Tuple[int, int], float] = {}

    # ---------- DB ----------
    async def _db(self):
        db = await aiosqlite.connect(DB_PATH)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS leveling (
                guild_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                xp       INTEGER NOT NULL DEFAULT 0,
                last_ts  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await db.commit()
        return db

    async def _get_stats(self, guild_id: int, user_id: int) -> Tuple[int, int]:
        async with await self._db() as db:
            cur = await db.execute("SELECT xp, last_ts FROM leveling WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            row = await cur.fetchone()
            if row:
                return int(row[0]), int(row[1])
        return 0, 0

    async def _add_xp(self, guild: discord.Guild, member: discord.Member, delta: int) -> Tuple[int, int, bool]:
        """
        Returns new_xp, new_level, leveled_up
        """
        gid, uid = guild.id, member.id
        async with await self._db() as db:
            # fetch
            cur = await db.execute("SELECT xp, last_ts FROM leveling WHERE guild_id=? AND user_id=?", (gid, uid))
            row = await cur.fetchone()
            if row:
                xp, last_ts = int(row[0]), int(row[1])
            else:
                xp, last_ts = 0, 0

            before_lvl = level_from_xp(xp)
            new_xp = max(0, xp + max(0, delta))
            new_lvl = level_from_xp(new_xp)
            leveled = new_lvl > before_lvl

            now_ts = int(time.time())
            await db.execute(
                "INSERT INTO leveling(guild_id, user_id, xp, last_ts) VALUES(?,?,?,?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET xp=excluded.xp, last_ts=excluded.last_ts",
                (gid, uid, new_xp, now_ts)
            )
            await db.commit()

        return new_xp, new_lvl, leveled

    async def _maybe_award_role(self, member: discord.Member, new_level: int):
        """
        If LEVEL_ROLE_<N> entries exist, try to give the highest role the user qualifies for.
        """
        if not LEVEL_ROLE_NAMES:
            return

        # find max level the member qualifies for with a configured role
        eligible: List[int] = [lvl for lvl in LEVEL_ROLE_NAMES.keys() if new_level >= lvl]
        if not eligible:
            return
        target_lvl = max(eligible)
        role_name = LEVEL_ROLE_NAMES[target_lvl]
        role = discord.utils.get(member.guild.roles, name=role_name)
        if not role:
            return

        me = member.guild.me
        if not me or not me.guild_permissions.manage_roles or role >= me.top_role:
            return  # cannot manage this role

        if role not in member.roles:
            try:
                await member.add_roles(role, reason=f"Level reward: reached L{target_lvl}")
            except Exception:
                pass

    async def _announce_levelup(self, channel: discord.abc.Messageable, member: discord.Member, level: int):
        if not LEVEL_ANNOUNCE:
            return
        try:
            e = discord.Embed(
                title="🎉 Level Up!",
                description=f"{member.mention} reached **Level {level}**",
                color=discord.Color.gold()
            )
            await channel.send(embed=e)
        except Exception:
            pass

    # ---------- Listeners ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore DMs, bots, and missing guilds
        if not message.guild or message.author.bot:
            return

        member = message.author
        gid, uid = message.guild.id, member.id

        # simple cooldown per (guild,user)
        key = (gid, uid)
        now = time.time()
        last = self._cooldown.get(key, 0)
        if now - last < AWARD_COOLDOWN:
            return

        # basic anti-spam: ignore ultra-short messages
        content = (message.content or "").strip()
        if len(content) < 3 and not message.attachments:
            return

        # award random XP in range
        delta = random.randint(AWARD_MIN, AWARD_MAX)

        # update cooldown
        self._cooldown[key] = now

        # persist
        new_xp, new_lvl, leveled = await self._add_xp(message.guild, member, delta)

        # announce + roles
        if leveled:
            await self._announce_levelup(message.channel, member, new_lvl)
            await self._maybe_award_role(member, new_lvl)

    # ---------- Commands ----------
    @GUILD_DEC
    @app_commands.command(name="rank", description="Show your (or another member’s) level and XP.")
    @app_commands.describe(member="Member to check (optional)")
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        xp, _ = await self._get_stats(interaction.guild_id, member.id)
        lvl, xp_in, xp_req = progress_to_next(xp)
        bar = progress_bar(xp_in, xp_req, width=16)

        e = discord.Embed(
            title=f"🏅 Rank — {member.display_name}",
            description=f"Level **{lvl}**  |  XP **{xp}**",
            color=discord.Color.blurple()
        )
        e.add_field(name="Progress", value=f"`{bar}`  {xp_in}/{xp_req} XP to next level", inline=False)
        e.set_thumbnail(url=member.display_avatar.url if member.display_avatar else discord.Embed.Empty)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="top", description="Show the top members by XP.")
    @app_commands.describe(limit="How many users to show (default 10, max 25)")
    async def top(self, interaction: discord.Interaction, limit: int = 10):
        limit = max(1, min(25, limit))
        async with await self._db() as db:
            cur = await db.execute(
                "SELECT user_id, xp FROM leveling WHERE guild_id=? ORDER BY xp DESC LIMIT ?",
                (interaction.guild_id, limit)
            )
            rows = await cur.fetchall()

        if not rows:
            return await interaction.response.send_message("No data yet — start chatting to earn XP!", ephemeral=True)

        lines = []
        for idx, (uid, xp) in enumerate(rows, start=1):
            member = interaction.guild.get_member(uid)
            name = member.display_name if member else f"User {uid}"
            lvl = level_from_xp(int(xp))
            lines.append(f"**{idx}.** {name} — L{lvl} ({xp} XP)")

        e = discord.Embed(title="🏆 Leaderboard", description="\n".join(lines), color=discord.Color.gold())
        await interaction.response.send_message(embed=e)

    # Optional: admin test tool to grant XP
    @GUILD_DEC
    @app_commands.command(name="level_givexp", description="(Admin) Give XP to a member (testing).")
    @app_commands.describe(member="Member to grant XP", xp="Amount of XP to add")
    async def level_givexp(self, interaction: discord.Interaction, member: discord.Member, xp: int):
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("🚫 You need **Manage Server** or **Manage Roles**.", ephemeral=True)

        if xp <= 0:
            return await interaction.response.send_message("XP must be positive.", ephemeral=True)

        new_xp, new_lvl, leveled = await self._add_xp(interaction.guild, member, xp)
        msg = f"Added **{xp} XP** to {member.mention}. New total: **{new_xp} XP** (L{new_lvl})."
        if leveled:
            await self._maybe_award_role(member, new_lvl)
            msg += " 🎉 Level up!"
        await interaction.response.send_message(msg, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
