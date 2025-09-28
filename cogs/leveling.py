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

# ---- Curve & XP config ----
LEVEL_BASE = float(os.getenv("LEVEL_BASE", "100") or 100)   # xp_needed(level) = BASE * level^EXP
LEVEL_EXP  = float(os.getenv("LEVEL_EXP", "1.5") or 1.5)

AWARD_COOLDOWN = int(os.getenv("LEVEL_COOLDOWN_SEC", "60") or 60)
AWARD_MIN = int(os.getenv("LEVEL_XP_MIN", "10") or 10)
AWARD_MAX = int(os.getenv("LEVEL_XP_MAX", "20") or 20)

LEVEL_ANNOUNCE = (os.getenv("LEVEL_ANNOUNCE", "true").strip().lower() in {"1","true","yes","on"})

DAILY_BONUS_BASE = int(os.getenv("LEVEL_DAILY_BONUS", "250") or 250)
STREAK_PCT = float(os.getenv("LEVEL_STREAK_PCT", "0.10") or 0.10)  # +10% per day
STREAK_MAX = int(os.getenv("LEVEL_STREAK_MAX", "7") or 7)

KEEP_PREV = (os.getenv("LEVEL_KEEP_PREVIOUS", "false").strip().lower() in {"1","true","yes","on"})

# Channel boosts: CSV "channelId:multiplier,channelId:multiplier"
def _parse_channel_boosts() -> Dict[int, float]:
    raw = (os.getenv("LEVEL_CHANNEL_BOOSTS") or "").strip()
    boosts: Dict[int, float] = {}
    if not raw:
        return boosts
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        cid_s, mult_s = part.split(":", 1)
        try:
            cid = int(cid_s.strip())
            mult = float(mult_s.strip())
            if mult > 0:
                boosts[cid] = mult
        except Exception:
            continue
    return boosts

CHANNEL_BOOSTS = _parse_channel_boosts()

# Optional role rewards from env: LEVEL_ROLE_5=Medic, etc.
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
    return dict(sorted(mapping.items(), key=lambda kv: kv[0]))

LEVEL_ROLE_NAMES = _load_level_roles_from_env()

# Guild scoping for slash command fast sync
_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

# ------------- Level curve helpers -------------
def xp_needed_for_level(level: int) -> int:
    """XP required to go from (level-1) -> level."""
    if level <= 1:
        return int(LEVEL_BASE)
    return int(round(LEVEL_BASE * (level ** LEVEL_EXP)))

def level_from_xp(xp: int, max_level: int = 200) -> int:
    """Invert XP -> level using incremental search."""
    if xp <= 0:
        return 1
    lvl = 1
    while lvl < max_level:
        need = xp_needed_for_level(lvl + 1)
        if xp < need:
            break
        xp -= need
        lvl += 1
    return max(1, lvl)

def progress_to_next(xp_total: int) -> Tuple[int, int, int]:
    """
    Returns (level, xp_in_level, xp_required_for_next).
    xp_total is the member's total accumulated XP.
    """
    lvl = 1
    rem = xp_total
    while True:
        need = xp_needed_for_level(lvl + 1)
        if rem < need:
            return lvl, rem, need
        rem -= need
        lvl += 1

def progress_bar(xp_in: int, xp_req: int, width: int = 16) -> str:
    fill = int((xp_in / max(1, xp_req)) * width)
    return "█" * fill + "░" * (width - fill)

def _xp_role_names() -> set[str]:
    return {name for name in LEVEL_ROLE_NAMES.values() if name}

# ------------- Cog -------------
class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cooldown: Dict[Tuple[int, int], float] = {}  # (guild_id, user_id) -> last_ts

    # ---------- DB ----------
    async def _db(self):
        db = await aiosqlite.connect(DB_PATH)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS leveling (
                guild_id  INTEGER NOT NULL,
                user_id   INTEGER NOT NULL,
                xp        INTEGER NOT NULL DEFAULT 0,
                last_ts   INTEGER NOT NULL DEFAULT 0,
                last_daily_ts INTEGER NOT NULL DEFAULT 0,
                streak_count   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        # add columns if older schema
        try: await db.execute("ALTER TABLE leveling ADD COLUMN last_daily_ts INTEGER NOT NULL DEFAULT 0")
        except Exception: pass
        try: await db.execute("ALTER TABLE leveling ADD COLUMN streak_count INTEGER NOT NULL DEFAULT 0")
        except Exception: pass
        await db.commit()
        return db

    async def _get_stats(self, guild_id: int, user_id: int) -> Tuple[int, int, int, int]:
        async with await self._db() as db:
            cur = await db.execute(
                "SELECT xp, last_ts, last_daily_ts, streak_count FROM leveling WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)
            )
            row = await cur.fetchone()
            if row:
                return int(row[0]), int(row[1]), int(row[2]), int(row[3])
        return 0, 0, 0, 0

    async def _write_stats(self, guild_id: int, user_id: int, xp: int, last_ts: int, last_daily_ts: int, streak: int):
        async with await self._db() as db:
            await db.execute(
                "INSERT INTO leveling(guild_id, user_id, xp, last_ts, last_daily_ts, streak_count) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET xp=excluded.xp, last_ts=excluded.last_ts, "
                "last_daily_ts=excluded.last_daily_ts, streak_count=excluded.streak_count",
                (guild_id, user_id, xp, last_ts, last_daily_ts, streak)
            )
            await db.commit()

    # ---------- XP operations ----------
    def _channel_multiplier(self, channel_id: int) -> float:
        return float(CHANNEL_BOOSTS.get(channel_id, 1.0))

    async def _add_xp(self, guild: discord.Guild, member: discord.Member, delta: int) -> Tuple[int, int, bool]:
        gid, uid = guild.id, member.id
        xp, last_ts, last_daily_ts, streak = await self._get_stats(gid, uid)

        before_level = level_from_xp(xp)
        new_total = max(0, xp + max(0, delta))
        new_level = level_from_xp(new_total)
        leveled = new_level > before_level

        now_ts = int(time.time())
        await self._write_stats(gid, uid, new_total, now_ts, last_daily_ts, streak)

        return new_total, new_level, leveled

    async def _grant_daily(self, guild: discord.Guild, member: discord.Member) -> Tuple[int, int, int]:
        gid, uid = guild.id, member.id
        xp, last_ts, last_daily_ts, streak = await self._get_stats(gid, uid)
        now = int(time.time())
        today = now // 86400
        last_day = last_daily_ts // 86400 if last_daily_ts else -1

        if last_day == today:
            return 0, xp, streak

        if last_day == today - 1:
            streak = min(STREAK_MAX, streak + 1)
        else:
            streak = 1

        bonus = int(round(DAILY_BONUS_BASE * (1.0 + streak * STREAK_PCT)))
        new_total = xp + bonus
        await self._write_stats(gid, uid, new_total, last_ts, now, streak)
        return bonus, new_total, streak

    async def _maybe_award_role(self, member: discord.Member, new_level: int):
        if not LEVEL_ROLE_NAMES:
            return
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
            return

        if role not in member.roles:
            try:
                await member.add_roles(role, reason=f"Level reward: reached L{target_lvl}")
            except Exception:
                pass

        if not KEEP_PREV:
            await self._prune_lower_xp_roles(member, role.name)

    async def _prune_lower_xp_roles(self, member: discord.Member, keep_name: str):
        names = _xp_role_names()
        if not names:
            return
        to_remove = [r for r in member.roles if r.name in names and r.name != keep_name]
        if not to_remove:
            return
        me = member.guild.me
        if not me or not me.guild_permissions.manage_roles:
            return
        to_remove = [r for r in to_remove if r < me.top_role]
        if to_remove:
            try:
                await member.remove_roles(*to_remove, reason=f"Leveling: keep highest rank ({keep_name})")
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
    @commands.Cog.listener())
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        member = message.author
        gid, uid = message.guild.id, member.id

        content = (message.content or "").strip()
        if len(content) < 3 and not message.attachments:
            return

        now = time.time()
        last = getattr(self, "_cooldown", {}).get((gid, uid), 0.0)
        if now - last < AWARD_COOLDOWN:
            return
        self._cooldown[(gid, uid)] = now

        base = random.randint(AWARD_MIN, AWARD_MAX)
        mult = self._channel_multiplier(message.channel.id)
        delta = int(round(base * mult))

        new_total, new_lvl, leveled = await self._add_xp(message.guild, member, delta)
        if leveled:
            await self._announce_levelup(message.channel, member, new_lvl)
            await self._maybe_award_role(member, new_lvl)

    # ---------- Commands ----------
    @GUILD_DEC
    @app_commands.command(name="rank", description="Show your (or another member’s) level and XP.")
    @app_commands.describe(member="Member to check (optional)")
    async def rank(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        xp, _, _, _ = await self._get_stats(interaction.guild_id, member.id)
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

    @GUILD_DEC
    @app_commands.command(name="daily", description="Claim your daily XP bonus (streak increases your reward).")
    async def daily(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        bonus, new_total, streak = await self._grant_daily(interaction.guild, interaction.user)  # type: ignore
        if bonus == 0:
            return await interaction.followup.send("You’ve already claimed your daily bonus today. Come back tomorrow!", ephemeral=True)

        lvl_before = level_from_xp(new_total - bonus)
        lvl_after = level_from_xp(new_total)

        msg = f"✅ Daily claimed: **+{bonus} XP** (streak: {streak}/{STREAK_MAX})."
        if lvl_after > lvl_before:
            msg += f" 🎉 You reached **Level {lvl_after}**!"
            await self._maybe_award_role(interaction.user, lvl_after)  # type: ignore
        await interaction.followup.send(msg, ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="level_curve", description="Show the XP curve parameters and next thresholds.")
    async def level_curve(self, interaction: discord.Interaction):
        xp, _, _, _ = await self._get_stats(interaction.guild_id, interaction.user.id)
        lvl, xp_in, xp_req = progress_to_next(xp)
        upcoming = []
        cur_lvl = lvl
        for _ in range(5):
            need = xp_needed_for_level(cur_lvl + 1)
            upcoming.append(f"→ L{cur_lvl+1}: needs {need} XP from current level")
            cur_lvl += 1

        e = discord.Embed(title="📈 Level Curve", color=discord.Color.teal())
        e.add_field(name="Formula", value=f"xp_needed(level) = **{LEVEL_BASE:g} × level^{LEVEL_EXP:g}**", inline=False)
        e.add_field(name="Your Progress", value=f"Level **{lvl}** — `{xp_in}/{xp_req}` to next", inline=False)
        e.add_field(name="Upcoming", value="\n".join(upcoming), inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # NEW: list ladder titles from env
    @GUILD_DEC
    @app_commands.command(name="titles", description="Show the XP rank ladder (LEVEL_ROLE_*).")
    async def titles(self, interaction: discord.Interaction):
        if not LEVEL_ROLE_NAMES:
            return await interaction.response.send_message(
                "No ladder configured. Add `LEVEL_ROLE_*` keys to `.env` (e.g., `LEVEL_ROLE_5=Medic`).",
                ephemeral=True
            )
        lines = [f"**L{lvl}** — {name}" for lvl, name in LEVEL_ROLE_NAMES.items()]
        e = discord.Embed(title="🎮 XP Rank Ladder", description="\n".join(lines), color=discord.Color.purple())
        e.set_footer(text="Configure via LEVEL_ROLE_* in .env")
        await interaction.response.send_message(embed=e, ephemeral=True)

    # NEW: show active channel multipliers
    @GUILD_DEC
    @app_commands.command(name="boosts", description="Show active channel XP multipliers.")
    async def boosts(self, interaction: discord.Interaction):
        if not CHANNEL_BOOSTS:
            return await interaction.response.send_message("No channel boosts configured.", ephemeral=True)
        lines = []
        for cid, mult in CHANNEL_BOOSTS.items():
            ch = interaction.guild.get_channel(cid)
            label = ch.mention if isinstance(ch, discord.TextChannel) else f"`#{cid}`"
            lines.append(f"{label} — x{mult:g}")
        e = discord.Embed(title="⚡ Channel XP Boosts", description="\n".join(lines), color=discord.Color.brand_green())
        e.set_footer(text="Configure via LEVEL_CHANNEL_BOOSTS in .env")
        await interaction.response.send_message(embed=e, ephemeral=True)

    # Admin test: grant XP
    @GUILD_DEC
    @app_commands.command(name="level_givexp", description="(Admin) Give XP to a member (testing).")
    @app_commands.describe(member="Member to grant XP", xp="Amount of XP to add")
    async def level_givexp(self, interaction: discord.Interaction, member: discord.Member, xp: int):
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.manage_roles:
            return await interaction.response.send_message("🚫 You need **Manage Server** or **Manage Roles**.", ephemeral=True)
        if xp <= 0:
            return await interaction.response.send_message("XP must be positive.", ephemeral=True)

        new_total, new_lvl, leveled = await self._add_xp(interaction.guild, member, xp)
        msg = f"Added **{xp} XP** to {member.mention}. New total: **{new_total} XP** (L{new_lvl})."
        if leveled:
            await self._maybe_award_role(member, new_lvl)
            msg += " 🎉 Level up!"
        await interaction.response.send_message(msg, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
