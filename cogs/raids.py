# cogs/raids.py
import os
import re
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

def now_utc():
    return datetime.now(timezone.utc)

def short_ts(dt: datetime) -> str:
    return f"<t:{int(dt.timestamp())}:R>"

def raid_embed(title: str, url: str, ends_at: datetime, count: int = 0) -> discord.Embed:
    e = discord.Embed(
        title=f"⚔️ Raid: {title}",
        description=(
            f"**Target:** {url}\n"
            f"**Ends:** {short_ts(ends_at)}\n"
            f"**Participants done:** **{count}**"
        ),
        color=discord.Color.purple(),
    )
    e.set_footer(text="Boost the tweet with Like • Retweet • Reply • Quote")
    e.timestamp = now_utc()
    return e

def action_view(url: str, raid_id: int) -> discord.ui.View:
    # Build common x.com intents where possible
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(label="Open", url=url))
    v.add_item(discord.ui.Button(label="Like", url=url))      # Users must be logged in; direct 'intent' endpoints vary.
    v.add_item(discord.ui.Button(label="Retweet", url=url))
    v.add_item(discord.ui.Button(label="Reply", url=url))
    v.add_item(discord.ui.Button(label="Quote", url=url))
    v.add_item(DoneButton(raid_id=raid_id))
    return v

class DoneButton(discord.ui.Button):
    def __init__(self, raid_id: int):
        super().__init__(style=discord.ButtonStyle.success, label="✅ I’m done")
        self.raid_id = raid_id

    async def callback(self, interaction: discord.Interaction):
        assert interaction.user
        # record participation
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO raid_participants(raid_id, user_id, ts) VALUES (?, ?, ?)",
                (self.raid_id, interaction.user.id, int(now_utc().timestamp())),
            )
            await db.commit()
            # count new total
            cur = await db.execute("SELECT COUNT(*) FROM raid_participants WHERE raid_id=?", (self.raid_id,))
            (count,) = await cur.fetchone()

        # try to update the message embed count if it's a message component interaction
        try:
            msg = interaction.message
            if msg and msg.embeds:
                old = msg.embeds[0]
                # Rebuild with same title/url/ends
                title = old.title.replace("⚔️ Raid: ", "") if old.title else "Palaemon Raid"
                url = (old.description or "").split("**Target:** ", 1)[-1].split("\n", 1)[0].strip()
                # Parse ends from description line
                ends_line = [ln for ln in (old.description or "").splitlines() if ln.startswith("**Ends:**")]
                ends_at = now_utc()
                if ends_line:
                    # not strictly needed; we can leave relative time as-is
                    pass
                new_embed = raid_embed(title, url, ends_at, count=count)
                await interaction.response.edit_message(embed=new_embed, view=msg.components and msg.components[0] or None)
                return
        except Exception:
            pass

        # fallback ack
        if not interaction.response.is_done():
            await interaction.response.send_message("Thanks — recorded your participation! ✅", ephemeral=True)

class Raids(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.expiry_watch.start()

    def cog_unload(self):
        if self.expiry_watch.is_running():
            self.expiry_watch.cancel()

    # ---------- DB ----------
    async def _db(self):
        db = await aiosqlite.connect(DB_PATH)
        await db.execute("""
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
            )
        """)
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_raids_active
            ON raids(guild_id, active)
            WHERE active=1
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS raid_participants (
                raid_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                ts INTEGER NOT NULL,
                PRIMARY KEY (raid_id, user_id),
                FOREIGN KEY (raid_id) REFERENCES raids(id) ON DELETE CASCADE
            )
        """)
        await db.commit()
        return db

    async def _active_raid(self, guild_id: int):
        async with await self._db() as db:
            cur = await db.execute("SELECT id, channel_id, message_id, title, url, role_id, started_at, ends_at FROM raids WHERE guild_id=? AND active=1 LIMIT 1", (guild_id,))
            row = await cur.fetchone()
        return row  # or None

    async def _end_raid(self, raid_id: int):
        async with await self._db() as db:
            await db.execute("UPDATE raids SET active=0 WHERE id=?", (raid_id,))
            await db.commit()

    async def _participant_count(self, raid_id: int) -> int:
        async with await self._db() as db:
            cur = await db.execute("SELECT COUNT(*) FROM raid_participants WHERE raid_id=?", (raid_id,))
            (count,) = await cur.fetchone()
        return count

    # ---------- Helpers ----------
    def _find_raider_role(self, guild: discord.Guild) -> discord.Role | None:
        if RAID_ROLE_NAME:
            role = discord.utils.get(guild.roles, name=RAID_ROLE_NAME)
            if role:
                return role
        # last resort: highest role named “Raiders”
        for r in guild.roles:
            if r.name.lower() == "raiders":
                return r
        return None

    def _raid_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        ch = guild.get_channel(RAID_CHANNEL_ID) if RAID_CHANNEL_ID else None
        # fallback to a channel named raids
        if not ch:
            ch = discord.utils.get(guild.text_channels, name="raids") or discord.utils.get(guild.text_channels, name="raid")
        return ch

    async def _launch_raid(self, guild: discord.Guild, url: str, title: str, minutes: int) -> str:
        # End an existing active raid (one active per guild)
        act = await self._active_raid(guild.id)
        if act:
            await self._end_raid(act[0])

        channel = self._raid_channel(guild)
        if not channel:
            raise RuntimeError("No raid channel configured (set RAID_CHANNEL_ID or create #raids).")

        role = self._find_raider_role(guild)
        ends_at = now_utc() + timedelta(minutes=max(5, minutes))
        embed = raid_embed(title, url, ends_at, count=0)

        # Insert DB row first
        async with await self._db() as db:
            cur = await db.execute(
                "INSERT INTO raids(guild_id, channel_id, title, url, role_id, started_at, ends_at, active) VALUES(?,?,?,?,?,?,?,1)",
                (guild.id, channel.id, title, url, role.id if role else None, int(now_utc().timestamp()), int(ends_at.timestamp())),
            )
            raid_id = cur.lastrowid
            await db.commit()

        view = action_view(url, raid_id=raid_id)
        ping = role.mention if role else None
        msg = await channel.send(content=ping, embed=embed, view=view, allowed_mentions=discord.AllowedMentions(roles=True))

        # Save message_id
        async with await self._db() as db:
            await db.execute("UPDATE raids SET message_id=? WHERE id=?", (msg.id, raid_id))
            await db.commit()

        return f"Raid started in {channel.mention} — ends {short_ts(ends_at)}."

    # ---------- Auto-detect ----------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        if not (message.author.guild_permissions.manage_messages or message.author.guild_permissions.manage_guild):
            return  # only react to staff posts
        m = TW_URL_RE.search(message.content)
        if not m:
            return
        url = m.group(0)
        title = "Boost this tweet"
        try:
            note = await self._launch_raid(message.guild, url, title, DEFAULT_MINUTES)
            await message.reply(f"🚀 Raid launched automatically. {note}")
        except Exception as e:
            await message.reply(f"⚠️ Couldn’t auto-launch raid: `{e}`")

    # ---------- Slash Commands ----------
    @GUILD_DEC
    @app_commands.command(name="raid_new", description="Start a raid on a Twitter/X link.")
    @app_commands.describe(url="Link to the tweet", title="Short title for the raid", minutes="Duration in minutes (default from .env)")
    async def raid_new(self, inter: discord.Interaction, url: str, title: str, minutes: int | None = None):
        if not inter.user.guild_permissions.manage_messages and not inter.user.guild_permissions.manage_guild:
            return await inter.response.send_message("🚫 You need **Manage Messages** or **Manage Server**.", ephemeral=True)
        if not TW_URL_RE.search(url):
            return await inter.response.send_message("Provide a valid Twitter/X status URL.", ephemeral=True)

        await inter.response.defer(thinking=True, ephemeral=True)
        try:
            msg = await self._launch_raid(inter.guild, url, title, minutes or DEFAULT_MINUTES)
            await inter.followup.send(f"✅ {msg}", ephemeral=True)
        except Exception as e:
            await inter.followup.send(f"⚠️ Error: {e}", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="raid_ping", description="Re-ping the Raiders role on the active raid.")
    async def raid_ping(self, inter: discord.Interaction):
        if not inter.user.guild_permissions.manage_messages and not inter.user.guild_permissions.manage_guild:
            return await inter.response.send_message("🚫 You need **Manage Messages** or **Manage Server**.", ephemeral=True)

        await inter.response.defer(ephemeral=True)
        act = await self._active_raid(inter.guild_id)
        if not act:
            return await inter.followup.send("No active raid.", ephemeral=True)

        raid_id, channel_id, msg_id, title, url, role_id, *_ = act
        channel = inter.guild.get_channel(channel_id)
        role = inter.guild.get_role(role_id) if role_id else self._find_raider_role(inter.guild)
        if not channel:
            return await inter.followup.send("Raid channel no longer exists.", ephemeral=True)
        if not role:
            return await inter.followup.send("Raiders role not found.", ephemeral=True)

        await channel.send(role.mention, allowed_mentions=discord.AllowedMentions(roles=True))
        await inter.followup.send("🔔 Re-pinged Raiders.", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="raid_status", description="Show the active raid status.")
    async def raid_status(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        act = await self._active_raid(inter.guild_id)
        if not act:
            return await inter.followup.send("No active raid.", ephemeral=True)
        raid_id, channel_id, msg_id, title, url, role_id, started_at, ends_at = act
        count = await self._participant_count(raid_id)
        ends = datetime.fromtimestamp(ends_at, tz=timezone.utc)
        e = raid_embed(title, url, ends, count=count)
        await inter.followup.send(embed=e, ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="raid_done", description="Mark yourself as done for the current raid.")
    async def raid_done(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        act = await self._active_raid(inter.guild_id)
        if not act:
            return await inter.followup.send("No active raid.", ephemeral=True)
        raid_id = act[0]
        async with await self._db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO raid_participants(raid_id, user_id, ts) VALUES (?, ?, ?)",
                (raid_id, inter.user.id, int(now_utc().timestamp())),
            )
            await db.commit()
        count = await self._participant_count(raid_id)
        await inter.followup.send(f"✅ Recorded! Current done count: **{count}**", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="raid_end", description="End the active raid and post final results.")
    async def raid_end(self, inter: discord.Interaction):
        if not inter.user.guild_permissions.manage_messages and not inter.user.guild_permissions.manage_guild:
            return await inter.response.send_message("🚫 You need **Manage Messages** or **Manage Server**.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        act = await self._active_raid(inter.guild_id)
        if not act:
            return await inter.followup.send("No active raid.", ephemeral=True)

        raid_id, channel_id, msg_id, title, url, role_id, started_at, ends_at = act
        await self._end_raid(raid_id)
        channel = inter.guild.get_channel(channel_id)
        if channel:
            count = await self._participant_count(raid_id)
            e = discord.Embed(
                title=f"🏁 Raid Ended: {title}",
                description=f"Target: {url}\nParticipants done: **{count}**\nThanks everyone!",
                color=discord.Color.green(),
            )
            await channel.send(embed=e)
        await inter.followup.send("✅ Raid ended.", ephemeral=True)

    # ---------- Expiry watcher ----------
    @tasks.loop(minutes=1)
    async def expiry_watch(self):
        async with await self._db() as db:
            cur = await db.execute("SELECT id, guild_id, channel_id, title, url, ends_at FROM raids WHERE active=1")
            rows = await cur.fetchall()
        for raid_id, guild_id, channel_id, title, url, ends_at in rows:
            if now_utc().timestamp() >= ends_at:
                # auto end
                try:
                    guild = self.bot.get_guild(guild_id)
                    channel = guild.get_channel(channel_id) if guild else None
                    await self._end_raid(raid_id)
                    if channel:
                        count = await self._participant_count(raid_id)
                        e = discord.Embed(
                            title=f"🏁 Raid Ended: {title}",
                            description=f"Target: {url}\nParticipants done: **{count}**\nGood work!",
                            color=discord.Color.green(),
                        )
                        await channel.send(embed=e)
                except Exception:
                    pass

    @expiry_watch.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(Raids(bot))
