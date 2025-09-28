# cogs/raids.py
import os
import re
import random
import aiosqlite
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

# -------- Config (from .env) --------
DB_PATH = os.getenv("DB_PATH", "pal_bot.sqlite")
DEFAULT_MINUTES = int(os.getenv("RAID_DEFAULT_MIN", "30") or 30)
RAID_ROLE_NAME = os.getenv("RAID_ROLE_NAME", "Raiders")
RAID_CHANNEL_ID = int(os.getenv("RAID_CHANNEL_ID", "0") or 0)

_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

TW_URL_RE = re.compile(r"https?://(twitter\.com|x\.com)/[^/]+/status/(\d+)", re.IGNORECASE)

# Fun messages and emojis
RAID_EMOJIS = ["⚔️", "🚀", "💥", "⚡", "🔥", "💪", "🎯", "🌟"]
LAUNCH_MESSAGES = [
    "🚀 **RAID LAUNCHED!** Time to dominate!",
    "⚔️ **BATTLE STATIONS!** Let's crush this target!",
    "💥 **ASSAULT INCOMING!** Raiders, move out!",
    "🔥 **RAID FORCE DEPLOYED!** Show no mercy!",
    "⚡ **LIGHTNING STRIKE!** Fast and fierce!",
    "💪 **POWER SURGE!** Unleash the chaos!",
    "🎯 **TARGET ACQUIRED!** All units engage!"
]

COMPLETION_MESSAGES = [
    "🏆 **VICTORY ACHIEVED!** Outstanding work, Raiders!",
    "⭐ **MISSION ACCOMPLISHED!** You absolutely crushed it!",
    "🎉 **RAID COMPLETE!** Legendary performance!",
    "💎 **FLAWLESS EXECUTION!** The enemy never saw it coming!",
    "🔥 **TOTAL DOMINATION!** Another successful campaign!",
    "👑 **CHAMPIONS RISE!** Bow to the Raid Kings!",
    "⚡ **ELECTRIFYING FINISH!** Pure excellence!"
]

MOTIVATIONAL_QUOTES = [
    "💀 *\"Strike fear into their hearts!\"*",
    "🔥 *\"Let them feel our fury!\"*",
    "⚡ *\"Swift like lightning, fierce like thunder!\"*",
    "👑 *\"We are the storm they never saw coming!\"*",
    "💎 *\"Legends are made in moments like these!\"*",
    "🚀 *\"To infinity and beyond their expectations!\"*"
]

# ---------- Helpers ----------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def short_ts(dt: datetime) -> str:
    return f"<t:{int(dt.timestamp())}:R>"

def get_raid_color(count: int) -> discord.Color:
    """Dynamic color based on participation"""
    if count >= 20:
        return discord.Color.gold()  # Legendary
    elif count >= 15:
        return discord.Color.purple()  # Epic
    elif count >= 10:
        return discord.Color.blue()  # Rare
    elif count >= 5:
        return discord.Color.green()  # Common
    else:
        return discord.Color.red()  # Starting

def get_rank_emoji(count: int) -> str:
    """Get rank emoji based on participation"""
    if count >= 25:
        return "👑"  # Legendary
    elif count >= 20:
        return "💎"  # Diamond
    elif count >= 15:
        return "🏆"  # Gold
    elif count >= 10:
        return "🥈"  # Silver
    elif count >= 5:
        return "🥉"  # Bronze
    else:
        return "⭐"  # Recruit

def raid_embed(title: str, url: str, ends_at: datetime, count: int = 0, started_at: datetime = None) -> discord.Embed:
    raid_emoji = random.choice(RAID_EMOJIS)
    rank_emoji = get_rank_emoji(count)
    color = get_raid_color(count)
    
    # Progress bar visual
    progress_bar = create_progress_bar(count, 20)  # Target of 20 for full bar
    
    # Calculate time remaining
    now = now_utc()
    time_left = ends_at - now
    
    if time_left.total_seconds() <= 0:
        time_status = "⏰ **EXPIRED**"
    else:
        time_status = f"⏰ **ENDS:** {short_ts(ends_at)}"
    
    e = discord.Embed(
        title=f"{raid_emoji} **RAID: {title.upper()}** {raid_emoji}",
        color=color,
    )
    
    # Main description with visual flair
    description = f"""
**🎯 TARGET:** {url}
{time_status}
**{rank_emoji} WARRIORS DEPLOYED:** `{count}`

{progress_bar}

{random.choice(MOTIVATIONAL_QUOTES)}
    """.strip()
    
    e.description = description
    
    # Add tactical instructions
    e.add_field(
        name="📋 **BATTLE PLAN**",
        value=(
            "```\n"
            "🎯 ENGAGE TARGET\n"
            "❤️  LIKE & BOOST\n"
            "🔄 RETWEET FOR MAX IMPACT\n"
            "💬 REPLY WITH POWER\n"
            "🗨️  QUOTE WITH FURY\n"
            "✅ REPORT MISSION COMPLETE\n"
            "```"
        ),
        inline=False
    )
    
    # Add rank system info
    rank_info = get_rank_info(count)
    if rank_info:
        e.add_field(
            name="🏅 **RANK STATUS**",
            value=rank_info,
            inline=True
        )
    
    # Add time info
    if started_at:
        duration = ends_at - started_at
        duration_mins = int(duration.total_seconds() / 60)
        e.add_field(
            name="⏱️ **MISSION DURATION**",
            value=f"{duration_mins} minutes",
            inline=True
        )
    
    e.set_footer(
        text="⚔️ Palaemon Raid Force • Strike Fast, Strike Hard",
    )
    e.timestamp = now_utc()
    return e

def create_progress_bar(current: int, target: int = 20, length: int = 10) -> str:
    """Create a visual progress bar"""
    filled = min(current, target)
    progress = filled / target
    filled_blocks = int(progress * length)
    empty_blocks = length - filled_blocks
    
    bar = "█" * filled_blocks + "░" * empty_blocks
    percentage = int(progress * 100)
    
    if percentage >= 100:
        return f"🔥 `[{bar}]` **{percentage}%** 🔥 **MAXIMUM POWER!**"
    elif percentage >= 75:
        return f"⚡ `[{bar}]` **{percentage}%** ⚡ **ALMOST THERE!**"
    elif percentage >= 50:
        return f"💪 `[{bar}]` **{percentage}%** 💪 **GAINING MOMENTUM!**"
    elif percentage >= 25:
        return f"🚀 `[{bar}]` **{percentage}%** 🚀 **BUILDING FORCE!**"
    else:
        return f"⭐ `[{bar}]` **{percentage}%** ⭐ **RALLY THE TROOPS!**"

def get_rank_info(count: int) -> str:
    """Get rank information based on participation"""
    if count >= 25:
        return "👑 **LEGENDARY RAID** 👑\n*The stuff of legends!*"
    elif count >= 20:
        return "💎 **DIAMOND TIER** 💎\n*Absolutely crushing it!*"
    elif count >= 15:
        return "🏆 **GOLD STANDARD** 🏆\n*Exceptional performance!*"
    elif count >= 10:
        return "🥈 **SILVER FORCE** 🥈\n*Strong showing!*"
    elif count >= 5:
        return "🥉 **BRONZE BATTALION** 🥉\n*Good start!*"
    else:
        return "⭐ **RECRUIT LEVEL** ⭐\n*Every legend starts somewhere!*"

# ---------- Enhanced UI ----------
class DoneButton(discord.ui.Button):
    def __init__(self, raid_id: int):
        super().__init__(
            style=discord.ButtonStyle.success, 
            label="✅ MISSION COMPLETE",
            emoji="⚔️"
        )
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction):
        assert interaction.user
        await record_participation(self.raid_id, interaction.user.id)

        count = await participant_count(self.raid_id)
        
        # Celebration messages based on milestones
        celebration = ""
        if count == 1:
            celebration = "🎯 **FIRST BLOOD!** You led the charge!"
        elif count % 5 == 0:
            celebration = f"🔥 **{count} WARRIORS STRONG!** The force grows!"
        elif count >= 20:
            celebration = "👑 **LEGENDARY RAID STATUS ACHIEVED!** 👑"

        # Try to update the panel embed with correct timing
        try:
            msg = interaction.message
            if msg and msg.embeds:
                old = msg.embeds[0]
                title = (old.title or "").replace("⚔️ **RAID: ", "").replace("** ⚔️", "") or "Palaemon Raid"
                title = title.replace("🚀 **RAID: ", "").replace("💥 **RAID: ", "").replace("⚡ **RAID: ", "")
                
                # Get raid info from database to get correct end time
                async with aiosqlite.connect(DB_PATH) as db:
                    cur = await db.execute(
                        "SELECT url, started_at, ends_at FROM raids WHERE id=?", 
                        (self.raid_id,)
                    )
                    raid_data = await cur.fetchone()
                
                if raid_data:
                    url, started_ts, ends_ts = raid_data
                    ends_at = datetime.fromtimestamp(ends_ts, timezone.utc)
                    started_at = datetime.fromtimestamp(started_ts, timezone.utc)
                    
                    new_embed = raid_embed(title, url, ends_at, count=count, started_at=started_at)
                    new_view = action_view(url, raid_id=self.raid_id)
                    await interaction.response.edit_message(embed=new_embed, view=new_view)
                    
                    # Send celebration if there is one
                    if celebration:
                        await interaction.followup.send(celebration, ephemeral=True)
                    return
        except Exception as e:
            print(f"Failed to update embed: {e}")

        response = f"⚔️ **MISSION LOGGED!** Thanks for your service, warrior!\n{celebration}".strip()
        if not interaction.response.is_done():
            await interaction.response.send_message(response, ephemeral=True)


def action_view(url: str, raid_id: int) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    
    # Enhanced buttons with emojis and style
    v.add_item(discord.ui.Button(label="🎯 ENGAGE", url=url, style=discord.ButtonStyle.link))
    v.add_item(discord.ui.Button(label="❤️ LIKE", url=url, style=discord.ButtonStyle.link))
    v.add_item(discord.ui.Button(label="🔄 RETWEET", url=url, style=discord.ButtonStyle.link))
    v.add_item(discord.ui.Button(label="💬 REPLY", url=url, style=discord.ButtonStyle.link))
    v.add_item(discord.ui.Button(label="🗨️ QUOTE", url=url, style=discord.ButtonStyle.link))
    v.add_item(DoneButton(raid_id=raid_id))
    return v

# ---------- DB helpers (module-level so UI can use) ----------
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS raids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    role_id INTEGER,
    started_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
"""
CREATE_PARTICIPANTS_SQL = """
CREATE TABLE IF NOT EXISTS raid_participants (
    raid_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    PRIMARY KEY (raid_id, user_id),
    FOREIGN KEY (raid_id) REFERENCES raids(id) ON DELETE CASCADE
);
"""
CREATE_ACTIVE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_raids_active
ON raids(guild_id, active) WHERE active=1;
"""

async def ensure_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_SQL)
        await db.execute(CREATE_PARTICIPANTS_SQL)
        await db.execute(CREATE_ACTIVE_INDEX)
        await db.commit()

async def record_participation(raid_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO raid_participants(raid_id, user_id, ts) VALUES (?,?,?)",
            (raid_id, user_id, int(now_utc().timestamp())),
        )
        await db.commit()

async def participant_count(raid_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM raid_participants WHERE raid_id=?", (raid_id,))
        (count,) = await cur.fetchone()
    return count

# ---------- Enhanced Cog ----------
class Raids(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.expiry_watch.start()

    async def cog_load(self):
        await ensure_db()

    def cog_unload(self):
        if self.expiry_watch.is_running():
            self.expiry_watch.cancel()

    # ---------- Internals ----------
    async def _active_raid(self, guild_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT id, channel_id, message_id, title, url, role_id, started_at, ends_at "
                "FROM raids WHERE guild_id=? AND active=1 LIMIT 1",
                (guild_id,),
            )
            return await cur.fetchone()

    async def _end_raid(self, raid_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE raids SET active=0 WHERE id=?", (raid_id,))
            await db.commit()

    def _find_raider_role(self, guild: discord.Guild) -> discord.Role | None:
        if RAID_ROLE_NAME:
            role = discord.utils.get(guild.roles, name=RAID_ROLE_NAME)
            if role: return role
        for r in guild.roles:
            if r.name.lower() == "raiders":
                return r
        return None

    def _raid_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        ch = guild.get_channel(RAID_CHANNEL_ID) if RAID_CHANNEL_ID else None
        if not ch:
            ch = discord.utils.get(guild.text_channels, name="raids") or discord.utils.get(guild.text_channels, name="raid")
        return ch

    async def _launch_raid(self, guild: discord.Guild, url: str, title: str, minutes: int) -> str:
        # End any existing active raid first
        act = await self._active_raid(guild.id)
        if act:
            await self._end_raid(act[0])

        channel = self._raid_channel(guild)
        if not channel:
            raise RuntimeError("🚫 No raid channel configured! Set RAID_CHANNEL_ID or create #raids channel.")

        role = self._find_raider_role(guild)
        started_at = now_utc()
        ends_at = started_at + timedelta(minutes=max(5, minutes))
        embed = raid_embed(title, url, ends_at, count=0, started_at=started_at)

        # Insert DB row to get raid_id
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "INSERT INTO raids(guild_id, channel_id, title, url, role_id, started_at, ends_at, active) "
                "VALUES(?,?,?,?,?,?,?,1)",
                (guild.id, channel.id, title, url, role.id if role else None,
                 int(started_at.timestamp()), int(ends_at.timestamp())),
            )
            raid_id = cur.lastrowid
            await db.commit()

        # Enhanced launch message
        launch_msg = random.choice(LAUNCH_MESSAGES)
        ping_content = f"{launch_msg}\n{role.mention if role else '@everyone'}"

        # Send the epic panel
        view = action_view(url, raid_id=raid_id)
        panel_msg = await channel.send(
            content=ping_content,
            embed=embed,
            view=view,
            allowed_mentions=discord.AllowedMentions(roles=True, everyone=True),
        )

        # Create thread with style
        try:
            thread = await channel.create_thread(
                name=f"⚔️ {title} • Battle Discussion",
                type=discord.ChannelType.public_thread,
                message=panel_msg,
            )
            thread_msg = f"""
🚀 **RAID COMMAND CENTER ACTIVATED!**

**Target:** {url}
**Mission Duration:** {minutes} minutes
**Ends:** {short_ts(ends_at)}
**Status:** 🟢 **ACTIVE ASSAULT**

📋 **Battle Orders:**
• Coordinate your attacks here
• Share screenshots of your engagement
• Rally the troops for maximum impact!

⚔️ **FOR PALAEMON!** ⚔️
            """.strip()
            await thread.send(thread_msg)
        except (discord.HTTPException, discord.Forbidden):
            pass

        # Save message id
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE raids SET message_id=? WHERE id=?", (panel_msg.id, raid_id))
            await db.commit()

        return f"🚀 **RAID DEPLOYED** in {channel.mention} • Mission ends {short_ts(ends_at)}"

    # ---------- Auto-detect with flair ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        if not (message.author.guild_permissions.manage_messages or message.author.guild_permissions.manage_guild):
            return
        m = TW_URL_RE.search(message.content)
        if not m:
            return
        url = m.group(0)
        title = "Boost this tweet"
        try:
            note = await self._launch_raid(message.guild, url, title, DEFAULT_MINUTES)
            await message.reply(f"⚡ **AUTO-RAID INITIATED!** {note}")
        except Exception as e:
            await message.reply(f"💥 **RAID DEPLOYMENT FAILED:** `{e}`")

    # ---------- Enhanced Slash Commands ----------
    @GUILD_DEC
    @app_commands.command(name="raid_new", description="🚀 Launch a devastating raid on a Twitter/X target!")
    @app_commands.describe(
        url="🎯 Target URL (Twitter/X link)", 
        title="⚔️ Battle name/description", 
        minutes="⏰ Mission duration (minutes)"
    )
    async def raid_new(self, inter: discord.Interaction, url: str, title: str, minutes: int | None = None):
        if not inter.user.guild_permissions.manage_messages and not inter.user.guild_permissions.manage_guild:
            return await inter.response.send_message("🚫 **ACCESS DENIED!** You need **Manage Messages** or **Manage Server** to launch raids.", ephemeral=True)
        if not TW_URL_RE.search(url):
            return await inter.response.send_message("❌ **INVALID TARGET!** Provide a valid Twitter/X status URL.", ephemeral=True)

        await inter.response.defer(thinking=True, ephemeral=True)
        try:
            msg = await self._launch_raid(inter.guild, url, title, minutes or DEFAULT_MINUTES)
            await inter.followup.send(f"⚔️ **RAID COMMAND EXECUTED!**\n{msg}", ephemeral=True)
        except Exception as e:
            await inter.followup.send(f"💥 **MISSION FAILED:** {e}", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="raid_ping", description="🔔 Rally the troops! Re-ping Raiders for the active raid.")
    async def raid_ping(self, inter: discord.Interaction):
        if not inter.user.guild_permissions.manage_messages and not inter.user.guild_permissions.manage_guild:
            return await inter.response.send_message("🚫 **ACCESS DENIED!** Command staff only.", ephemeral=True)

        await inter.response.defer(ephemeral=True)
        act = await self._active_raid(inter.guild_id)
        if not act:
            return await inter.followup.send("📭 **NO ACTIVE RAIDS** found.", ephemeral=True)

        raid_id, channel_id, msg_id, title, url, role_id, *_ = act
        channel = inter.guild.get_channel(channel_id)
        role = inter.guild.get_role(role_id) if role_id else self._find_raider_role(inter.guild)
        if not channel:
            return await inter.followup.send("💀 **CHANNEL DESTROYED** - Raid channel no longer exists.", ephemeral=True)
        if not role:
            return await inter.followup.send("👻 **RAIDERS MISSING** - Role not found.", ephemeral=True)

        rally_messages = [
            f"🔥 **RALLY CALL!** {role.mention} The battle rages on!",
            f"⚡ **REINFORCEMENTS NEEDED!** {role.mention} Join the fight!",
            f"💪 **ALL HANDS ON DECK!** {role.mention} Victory awaits!"
        ]
        
        await channel.send(random.choice(rally_messages), allowed_mentions=discord.AllowedMentions(roles=True))
        await inter.followup.send("🔔 **TROOPS RALLIED!** Battle cry sent.", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="raid_status", description="📊 Check the current raid battlefield status.")
    async def raid_status(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        act = await self._active_raid(inter.guild_id)
        if not act:
            embed = discord.Embed(
                title="🏴 **NO ACTIVE RAIDS**",
                description="*The battlefield is quiet... for now.*\n\nUse `/raid_new` to launch an assault!",
                color=discord.Color.greyple()
            )
            return await inter.followup.send(embed=embed, ephemeral=True)
            
        raid_id, channel_id, msg_id, title, url, role_id, started_at, ends_at = act
        count = await participant_count(raid_id)
        ends = datetime.fromtimestamp(ends_at, tz=timezone.utc)
        started = datetime.fromtimestamp(started_at, tz=timezone.utc)
        e = raid_embed(title, url, ends, count=count, started_at=started)
        await inter.followup.send(embed=e, ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="raid_done", description="✅ Report your mission complete!")
    async def raid_done(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        act = await self._active_raid(inter.guild_id)
        if not act:
            return await inter.followup.send("📭 **NO ACTIVE MISSIONS** - Stand by for orders.", ephemeral=True)
        raid_id = act[0]
        await record_participation(raid_id, inter.user.id)
        count = await participant_count(raid_id)
        
        celebration = f"⚔️ **MISSION LOGGED, WARRIOR!**\nCurrent force strength: **{count}** raiders deployed!\n{get_rank_emoji(count)} Keep fighting!"
        await inter.followup.send(celebration, ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="raid_end", description="🏁 End the current raid and declare victory!")
    async def raid_end(self, inter: discord.Interaction):
        if not inter.user.guild_permissions.manage_messages and not inter.user.guild_permissions.manage_guild:
            return await inter.response.send_message("🚫 **ACCESS DENIED!** Command staff only.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        act = await self._active_raid(inter.guild_id)
        if not act:
            return await inter.followup.send("📭 **NO ACTIVE RAIDS** to end.", ephemeral=True)

        raid_id, channel_id, msg_id, title, url, role_id, started_at, ends_at = act
        await self._end_raid(raid_id)
        channel = inter.guild.get_channel(channel_id)
        if channel:
            count = await participant_count(raid_id)
            completion_msg = random.choice(COMPLETION_MESSAGES)
            rank_emoji = get_rank_emoji(count)
            
            e = discord.Embed(
                title=f"🏆 **VICTORY ACHIEVED!** 🏆",
                description=f"""
**{completion_msg}**

**Mission:** {title}
**Target:** {url}
**{rank_emoji} Final Warriors:** **{count}**

{create_progress_bar(count, 20)}

*The battlefield is ours! Well fought, Raiders!*
                """.strip(),
                color=discord.Color.gold(),
            )
            e.set_footer(text="⚔️ Another glorious victory for Palaemon! • GG Raiders!")
            await channel.send(embed=e)
        await inter.followup.send("🏁 **RAID CONCLUDED!** Victory declared.", ephemeral=True)

    # ---------- Enhanced Expiry watcher ----------
    @tasks.loop(minutes=1)
    async def expiry_watch(self):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("SELECT id, guild_id, channel_id, title, url, ends_at FROM raids WHERE active=1")
                rows = await cur.fetchall()
        except Exception:
            return

        for raid_id, guild_id, channel_id, title, url, ends_at in rows:
            if now_utc().timestamp() >= ends_at:
                try:
                    guild = self.bot.get_guild(guild_id)
                    channel = guild.get_channel(channel_id) if guild else None
                    await self._end_raid(raid_id)
                    if channel:
                        count = await participant_count(raid_id)
                        completion_msg = random.choice(COMPLETION_MESSAGES)
                        rank_emoji = get_rank_emoji(count)
                        
                        e = discord.Embed(
                            title="⏰ **TIME'S UP! MISSION COMPLETE!** ⏰",
                            description=f"""
**{completion_msg}**

**Mission:** {title}
**Target:** {url}
**{rank_emoji} Warriors Who Answered The Call:** **{count}**

{create_progress_bar(count, 20)}

*Time may be up, but legends live forever!*
                            """.strip(),
                            color=discord.Color.gold(),
                        )
                        e.set_footer(text="⚔️ Auto-completed by Raid Command • Thank you for your service!")
                        await channel.send(embed=e)
                except Exception:
                    pass

    @expiry_watch.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Raids(bot))
