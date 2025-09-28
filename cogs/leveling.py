# cogs/leveling.py
import os, random, time, asyncio
import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
from datetime import datetime, timezone, date

# ---------- ENV ----------
DB_PATH = os.getenv("DB_PATH", "pal_bot.sqlite")

LEVEL_ANNOUNCE = (os.getenv("LEVEL_ANNOUNCE", "true").lower() in {"1","true","yes","on"})
LEVEL_COOLDOWN = int(os.getenv("LEVEL_COOLDOWN_SEC", "60") or 60)
XP_MIN = int(os.getenv("LEVEL_XP_MIN", "15") or 15)
XP_MAX = int(os.getenv("LEVEL_XP_MAX", "25") or 25)

# Curve
LV_BASE = int(os.getenv("LEVEL_BASE", "100") or 100)
LV_EXP = float(os.getenv("LEVEL_EXP", "1.5") or 1.5)

# Daily / streaks
DAILY_BONUS = int(os.getenv("LEVEL_DAILY_BONUS", "250") or 250)
STREAK_PCT = float(os.getenv("LEVEL_STREAK_PCT", "0.10") or 0.10)   # +10% per day
STREAK_MAX = int(os.getenv("LEVEL_STREAK_MAX", "7") or 7)

KEEP_PREV = (os.getenv("LEVEL_KEEP_PREVIOUS", "false").lower() in {"1","true","yes","on"})

# Guild scoping for slash command fast sync
_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

# Channel boosts: "channelId:multiplier,..."
def parse_boosts() -> dict[int, float]:
    raw = os.getenv("LEVEL_CHANNEL_BOOSTS", "") or ""
    out: dict[int, float] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part: continue
        try:
            cid, mult = part.split(":")
            out[int(cid.strip())] = float(mult.strip())
        except Exception:
            pass
    return out
BOOSTS = parse_boosts()

# Ladder: env keys like LEVEL_ROLE_5=Responder
def parse_titles() -> dict[int, str]:
    out: dict[int, str] = {}
    for k, v in os.environ.items():
        if not k.startswith("LEVEL_ROLE_"): continue
        try:
            lvl = int(k.split("_")[-1])
            if v.strip(): out[lvl] = v.strip()
        except Exception:
            continue
    return dict(sorted(out.items(), key=lambda kv: kv[0]))
TITLES = parse_titles()

# ---------- DB LAYER ----------
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS xp (
  guild_id    INTEGER NOT NULL,
  user_id     INTEGER NOT NULL,
  xp          INTEGER NOT NULL DEFAULT 0,
  level       INTEGER NOT NULL DEFAULT 0,
  last_xp_ts  INTEGER NOT NULL DEFAULT 0,
  last_daily  TEXT,
  streak      INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (guild_id, user_id)
);
"""

class XPStore:
    def __init__(self, path=DB_PATH):
        self.path = path
        self._lock = asyncio.Lock()

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(CREATE_SQL)
            await db.commit()

    async def get_row(self, guild_id: int, user_id: int):
        async with self._lock, aiosqlite.connect(self.path) as db:
            await db.execute(CREATE_SQL)
            cur = await db.execute("SELECT xp, level, last_xp_ts, last_daily, streak FROM xp WHERE guild_id=? AND user_id=?",
                                   (guild_id, user_id))
            row = await cur.fetchone()
            if row:
                return {"xp": row[0], "level": row[1], "last_ts": row[2], "last_daily": row[3], "streak": row[4]}
            await db.execute("INSERT INTO xp (guild_id, user_id) VALUES (?,?)", (guild_id, user_id))
            await db.commit()
            return {"xp": 0, "level": 0, "last_ts": 0, "last_daily": None, "streak": 0}

    async def save_row(self, guild_id: int, user_id: int, data: dict):
        fields = ["xp","level","last_xp_ts","last_daily","streak"]
        values = [data.get("xp",0), data.get("level",0), data.get("last_ts",0), data.get("last_daily"), data.get("streak",0),
                  guild_id, user_id]
        async with self._lock, aiosqlite.connect(self.path) as db:
            await db.execute(CREATE_SQL)
            await db.execute(f"UPDATE xp SET {', '.join([f+'=?' for f in fields])} WHERE guild_id=? AND user_id=?", values)
            await db.commit()

# ---------- HELPERS ----------
def total_xp_for_level(level: int) -> int:
    """Total XP required to *reach* this level (0 -> 0)."""
    total = 0
    for n in range(1, level+1):
        total += int(LV_BASE * (LV_EXP ** (n-1)))
    return total

def next_level_target(curr_level: int) -> int:
    return total_xp_for_level(curr_level + 1)

def level_from_xp(xp: int) -> int:
    lvl = 0
    while xp >= next_level_target(lvl):
        lvl += 1
        if lvl > 500: break
    return max(0, lvl)

def progress_bar(pct: float, size=12) -> str:
    filled = max(0, min(size, int(round(pct * size))))
    return "▰" * filled + "▱" * (size - filled)

async def grant_rank_role(member: discord.Member, new_level: int):
    if not TITLES: return
    # Find highest title <= new_level
    target_title = None
    for level, name in TITLES.items():
        if new_level >= level:
            target_title = name
    if not target_title: return

    guild = member.guild
    role = discord.utils.get(guild.roles, name=target_title)
    if not role: return

    # Manage roles safety
    me = guild.me
    if not me or not me.guild_permissions.manage_roles or role >= me.top_role:
        return

    to_add = [role]
    to_remove = []
    if not KEEP_PREV:
        # Remove other ladder roles
        ladder_names = set(TITLES.values()) - {target_title}
        to_remove = [r for r in member.roles if r.name in ladder_names and r < me.top_role]

    if to_remove:
        await member.remove_roles(*to_remove, reason="Level-up: remove lower ladder roles")
    await member.add_roles(*to_add, reason=f"Level-up: {target_title}")

# ---------- COG ----------
class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = XPStore()

    async def cog_load(self):
        await self.store.init()

    # XP on message
    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or not msg.guild: return
        now = int(time.time())

        # cooldown
        row = await self.store.get_row(msg.guild.id, msg.author.id)
        if now - int(row["last_ts"]) < LEVEL_COOLDOWN:
            return

        # base xp
        gain = random.randint(XP_MIN, XP_MAX)
        # channel boost
        mult = BOOSTS.get(msg.channel.id, 1.0)
        gain = int(gain * mult)

        # update
        new_xp = row["xp"] + gain
        new_level = level_from_xp(new_xp)
        leveled_up = new_level > row["level"]

        await self.store.save_row(msg.guild.id, msg.author.id,
                                  {"xp": new_xp, "level": new_level, "last_ts": now,
                                   "last_daily": row["last_daily"], "streak": row["streak"]})

        if leveled_up:
            await grant_rank_role(msg.author, new_level)
            if LEVEL_ANNOUNCE:
                try:
                    await msg.channel.send(f"🎉 {msg.author.mention} advanced to **Level {new_level}**!")
                except Exception:
                    pass

    # /daily
    @GUILD_DEC
    @app_commands.command(name="daily", description="Claim your daily XP bonus (streaks increase reward).")
    async def daily(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        member = inter.user
        g = inter.guild
        if not g: return await inter.followup.send("Guild only.", ephemeral=True)

        row = await self.store.get_row(g.id, member.id)
        today = date.today().isoformat()
        if row["last_daily"] == today:
            return await inter.followup.send("🗓️ You've already claimed today. Come back tomorrow!", ephemeral=True)

        # streak calc
        streak = row["streak"] or 0
        if row["last_daily"]:
            prev = date.fromisoformat(row["last_daily"])
            if (date.today() - prev).days == 1:
                streak = min(STREAK_MAX, streak + 1)
            else:
                streak = 1
        else:
            streak = 1

        bonus = DAILY_BONUS + int(DAILY_BONUS * STREAK_PCT * (streak - 1))
        new_xp = row["xp"] + bonus
        new_level = level_from_xp(new_xp)
        leveled = new_level > row["level"]

        await self.store.save_row(g.id, member.id,
                                  {"xp": new_xp, "level": new_level, "last_ts": row["last_ts"],
                                   "last_daily": today, "streak": streak})

        if leveled:
            await grant_rank_role(member, new_level)

        await inter.followup.send(
            f"✅ Daily claimed: **+{bonus} XP** (streak **{streak}/{STREAK_MAX}**) — "
            f"total **{new_xp} XP**, level **{new_level}**.", ephemeral=True)

    # /rank
    @GUILD_DEC
    @app_commands.command(name="rank", description="Show your current level progress.")
    async def rank(self, inter: discord.Interaction, member: discord.Member | None = None):
        member = member or inter.user
        row = await self.store.get_row(inter.guild.id, member.id)
        curr = row["level"]
        total = row["xp"]
        next_req = next_level_target(curr)
        prev_req = total_xp_for_level(curr)
        to_next = max(0, next_req - total)
        denom = max(1, next_req - prev_req)
        pct = (total - prev_req) / denom
        bar = progress_bar(pct)

        title = None
        for lvl, name in TITLES.items():
            if curr >= lvl:
                title = name

        e = discord.Embed(title=f"🏅 {member.display_name} — Level {curr}", color=discord.Color.gold())
        if title:
            e.add_field(name="Title", value=title, inline=True)
        e.add_field(name="XP", value=f"{total:,} / {next_req:,}", inline=True)
        e.add_field(name="Progress", value=f"{bar}  ({pct*100:.1f}%)", inline=False)
        e.set_footer(text=f"{to_next:,} XP to Level {curr+1}")
        await inter.response.send_message(embed=e, ephemeral=True)

    # /top
    @GUILD_DEC
    @app_commands.command(name="top", description="Show the server XP leaderboard (top 10).")
    async def top(self, inter: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(CREATE_SQL)
            cur = await db.execute("SELECT user_id, xp, level FROM xp WHERE guild_id=? ORDER BY xp DESC LIMIT 10", (inter.guild.id,))
            rows = await cur.fetchall()

        lines = []
        for i, (uid, xp, lvl) in enumerate(rows, start=1):
            user = inter.guild.get_member(uid) or f"<@{uid}>"
            name = user.display_name if isinstance(user, discord.Member) else str(user)
            lines.append(f"**{i}.** {name} — L{lvl} • {xp:,} XP")

        e = discord.Embed(title="🏆 Leaderboard — Top 10", description="\n".join(lines) or "No data yet.", color=discord.Color.purple())
        await inter.response.send_message(embed=e, ephemeral=True)

    # /titles
    @GUILD_DEC
    @app_commands.command(name="titles", description="Show the rank-title ladder.")
    async def titles(self, inter: discord.Interaction):
        if not TITLES:
            return await inter.response.send_message("No ladder configured. Add LEVEL_ROLE_* entries in `.env`.", ephemeral=True)
        lines = [f"L{lvl} — **{name}**" for lvl, name in TITLES.items()]
        e = discord.Embed(title="📜 XP Rank Ladder", description="\n".join(lines), color=discord.Color.blue())
        e.set_footer(text="Configure with LEVEL_ROLE_* in .env")
        await inter.response.send_message(embed=e, ephemeral=True)

    # /boosts
    @GUILD_DEC
    @app_commands.command(name="boosts", description="Show channel XP boosts.")
    async def boosts(self, inter: discord.Interaction):
        if not BOOSTS:
            return await inter.response.send_message("No channel boosts configured.", ephemeral=True)
        lines = [f"<#{cid}> — x{mult:g}" for cid, mult in BOOSTS.items()]
        await inter.response.send_message("⚡ Channel boosts:\n" + "\n".join(lines), ephemeral=True)

    # /level_curve
    @GUILD_DEC
    @app_commands.command(name="level_curve", description="Show XP targets for the next 10 levels.")
    async def level_curve(self, inter: discord.Interaction, start_level: int = 1):
        lines = []
        for i in range(start_level, start_level + 10):
            lines.append(f"L{i} → {total_xp_for_level(i):,} XP total")
        await inter.response.send_message("📈 XP curve:\n" + "\n".join(lines), ephemeral=True)

    # Admin: give XP
    @GUILD_DEC
    @app_commands.command(name="level_givexp", description="(Staff) Give XP to a member.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def level_givexp(self, inter: discord.Interaction, member: discord.Member, amount: int):
        row = await self.store.get_row(inter.guild.id, member.id)
        new_xp = max(0, row["xp"] + max(-10**9, min(10**9, amount)))
        new_level = level_from_xp(new_xp)
        await self.store.save_row(inter.guild.id, member.id,
                                  {"xp": new_xp, "level": new_level, "last_ts": row["last_ts"],
                                   "last_daily": row["last_daily"], "streak": row["streak"]})
        if new_level > row["level"]:
            await grant_rank_role(member, new_level)
        await inter.response.send_message(f"✅ Set {member.mention} to **{new_xp:,} XP** (L{new_level}).", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
