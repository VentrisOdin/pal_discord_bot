import os, re, time, asyncio, aiosqlite, urllib.parse
import discord
from discord.ext import commands, tasks
from discord import app_commands
from services.settings import Settings  # you already have this

DB = "pal_bot.sqlite"

# --- Guild scope decorator
_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

# --- DB schema
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS raids(
  raid_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  guild_id      INTEGER NOT NULL,
  channel_id    INTEGER NOT NULL,
  message_id    INTEGER,
  title         TEXT,
  tweet_url     TEXT NOT NULL,
  tweet_id      TEXT NOT NULL,
  started_at    INTEGER NOT NULL,
  ends_at       INTEGER,
  active        INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS raid_participants(
  raid_id       INTEGER NOT NULL,
  user_id       INTEGER NOT NULL,
  joined_at     INTEGER NOT NULL,
  done_at       INTEGER,
  PRIMARY KEY(raid_id, user_id)
);
"""

# --- tweet URL parsing (twitter.com / x.com)
TWEET_RE = re.compile(
    r"https?://(?:www\.)?(?:twitter|x)\.com/[^/]+/status/(\d+)",
    re.IGNORECASE,
)

def parse_tweet_id(url: str) -> str | None:
    m = TWEET_RE.match(url.strip())
    return m.group(1) if m else None

# --- Build intent links
def twitter_intents(tweet_id: str) -> dict:
    # Official-ish web intents
    return {
        "open": f"https://x.com/i/status/{tweet_id}",
        "like": f"https://twitter.com/intent/like?tweet_id={tweet_id}",
        "retweet": f"https://twitter.com/intent/retweet?tweet_id={tweet_id}",
        "reply": f"https://twitter.com/intent/tweet?in_reply_to={tweet_id}",
        # bonus: quote tweet prefill
        "quote": f"https://twitter.com/intent/tweet?url={urllib.parse.quote('https://x.com/i/status/'+tweet_id)}"
    }

def raid_embed(title: str, tweet_url: str, ends_at: int | None, joined: int, done: int) -> discord.Embed:
    desc = f"**Target:** {tweet_url}\n**Joined:** {joined} • **Done:** {done}"
    if ends_at:
        remaining = max(0, ends_at - int(time.time()))
        mins, secs = divmod(remaining, 60)
        desc += f"\n**Ends in:** {mins}m {secs}s"
    e = discord.Embed(title=f"⚔️ Raid — {title}", description=desc, color=discord.Color.gold())
    e.set_footer(text="Boost the tweet: Open → Like → Retweet → Reply → (optional Quote)")
    return e

class RaidView(discord.ui.View):
    def __init__(self, tweet_id: str, raid_id: int, ends_at: int | None):
        super().__init__(timeout=None)
        self.tweet_id = tweet_id
        self.raid_id = raid_id
        self.ends_at = ends_at
        self.urls = twitter_intents(tweet_id)

    @discord.ui.button(label="Open", style=discord.ButtonStyle.link, url="https://x.com")
    async def open_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.url = self.urls["open"]

    @discord.ui.button(label="Like", style=discord.ButtonStyle.link, url="https://twitter.com")
    async def like_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.url = self.urls["like"]

    @discord.ui.button(label="Retweet", style=discord.ButtonStyle.link, url="https://twitter.com")
    async def rt_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.url = self.urls["retweet"]

    @discord.ui.button(label="Reply", style=discord.ButtonStyle.link, url="https://twitter.com")
    async def reply_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.url = self.urls["reply"]

    @discord.ui.button(label="Quote", style=discord.ButtonStyle.link, url="https://twitter.com")
    async def quote_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.url = self.urls["quote"]

class Raids(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings = Settings()

    async def cog_load(self):
        await self.settings.init()
        async with aiosqlite.connect(DB) as db:
            for stmt in CREATE_SQL.strip().split(";"):
                s = stmt.strip()
                if s: await db.execute(s)
            await db.commit()
        if not self._ticker.is_running():
            self._ticker.start()

    def cog_unload(self):
        if self._ticker.is_running():
            self._ticker.cancel()

    # --- helpers
    async def _get_set(self, key: str, default: str | None = None) -> str | None:
        return await self.settings.get(key, os.getenv(key) if default is None else default)

    async def _resolve_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        ch_id = await self._get_set("RAID_CHANNEL_ID", "0")
        try:
            ch = guild.get_channel(int(ch_id))
            return ch if isinstance(ch, discord.TextChannel) else None
        except:  # noqa
            return None

    async def _role(self, guild: discord.Guild) -> discord.Role | None:
        name = await self._get_set("RAID_ROLE_NAME", "Raiders")
        return discord.utils.get(guild.roles, name=name)

    async def _counts(self, raid_id: int) -> tuple[int, int]:
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT COUNT(*), SUM(CASE WHEN done_at IS NOT NULL THEN 1 ELSE 0 END) FROM raid_participants WHERE raid_id=?", (raid_id,))
            row = await cur.fetchone()
        joined = int(row[0] or 0); done = int(row[1] or 0)
        return joined, done

    async def _active_raid(self, guild_id: int) -> dict | None:
        async with aiosqlite.connect(DB) as db:
            cur = await db.execute("SELECT raid_id,guild_id,channel_id,message_id,title,tweet_url,tweet_id,started_at,ends_at,active FROM raids WHERE guild_id=? AND active=1 ORDER BY raid_id DESC LIMIT 1", (guild_id,))
            row = await cur.fetchone()
        if not row: return None
        keys = ["raid_id","guild_id","channel_id","message_id","title","tweet_url","tweet_id","started_at","ends_at","active"]
        return dict(zip(keys, row))

    async def _set_message_id(self, raid_id: int, message_id: int):
        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE raids SET message_id=? WHERE raid_id=?", (message_id, raid_id))
            await db.commit()

    # --- Commands
    @GUILD_DEC
    @app_commands.command(name="raid_new", description="Start a tweet raid (pings Raiders).")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(url="Tweet URL (x.com/twitter.com)", title="Short title", minutes="Duration (default setting)")
    async def raid_new(self, inter: discord.Interaction, url: str, title: str | None = None, minutes: int | None = None):
        await inter.response.defer(ephemeral=True, thinking=True)

        tid = parse_tweet_id(url)
        if not tid:
            return await inter.followup.send("❌ Invalid tweet URL. Use a link like https://x.com/handle/status/1234", ephemeral=True)

        title = title or "Engage!"
        default_min = int(await self._get_set("RAID_DEFAULT_MIN", "30") or "30")
        minutes = minutes if (minutes and minutes > 0) else default_min
        now = int(time.time()); ends = now + minutes*60 if minutes else None

        ch = await self._resolve_channel(inter.guild) or inter.channel
        # create DB record
        async with aiosqlite.connect(DB) as db:
            await db.execute("""INSERT INTO raids(guild_id,channel_id,message_id,title,tweet_url,tweet_id,started_at,ends_at,active)
                                VALUES (?,?,?,?,?,?,?,?,1)""",
                             (inter.guild_id, ch.id, None, title, url, tid, now, ends))
            await db.commit()
            cur = await db.execute("SELECT last_insert_rowid()")
            raid_id = (await cur.fetchone())[0]

        joined, done = await self._counts(raid_id)
        e = raid_embed(title, url, ends, joined, done)
        view = RaidView(tid, raid_id, ends)

        role = await self._role(inter.guild)
        content = role.mention if role else None
        msg = await ch.send(content=content, embed=e, view=view, allowed_mentions=discord.AllowedMentions(roles=True))
        await self._set_message_id(raid_id, msg.id)

        await inter.followup.send(f"✅ Raid started in {ch.mention} (ID `{raid_id}`) — ends in {minutes}m.", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="raid_ping", description="Ping Raiders again on the active raid.")
    @app_commands.default_permissions(manage_guild=True)
    async def raid_ping(self, inter: discord.Interaction):
        raid = await self._active_raid(inter.guild_id)
        if not raid:
            return await inter.response.send_message("No active raid.", ephemeral=True)
        ch = inter.guild.get_channel(raid["channel_id"])
        role = await self._role(inter.guild)
        if not ch or not role:
            return await inter.response.send_message("Missing channel or raid role.", ephemeral=True)
        await ch.send(role.mention, allowed_mentions=discord.AllowedMentions(roles=True))
        await inter.response.send_message("🔔 Pinged Raiders.", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="raid_done", description="Mark yourself done for the current raid.")
    async def raid_done(self, inter: discord.Interaction):
        raid = await self._active_raid(inter.guild_id)
        if not raid:
            return await inter.response.send_message("No active raid.", ephemeral=True)
        if raid["ends_at"] and time.time() > raid["ends_at"]:
            return await inter.response.send_message("Raid already ended.", ephemeral=True)

        async with aiosqlite.connect(DB) as db:
            # ensure joined record exists
            await db.execute("""INSERT OR IGNORE INTO raid_participants(raid_id,user_id,joined_at)
                                VALUES (?,?,?)""", (raid["raid_id"], inter.user.id, int(time.time())))
            # set done time
            await db.execute("""UPDATE raid_participants SET done_at=? WHERE raid_id=? AND user_id=?""",
                             (int(time.time()), raid["raid_id"], inter.user.id))
            await db.commit()

        await inter.response.send_message("✅ Marked done. Thanks!", ephemeral=True)

        # update panel embed if we can
        try:
            ch = inter.guild.get_channel(raid["channel_id"])
            if ch and raid["message_id"]:
                msg = await ch.fetch_message(raid["message_id"])
                joined, done = await self._counts(raid["raid_id"])
                e = raid_embed(raid["title"], raid["tweet_url"], raid["ends_at"], joined, done)
                await msg.edit(embed=e)
        except Exception:
            pass

    @GUILD_DEC
    @app_commands.command(name="raid_status", description="Show active raid status.")
    async def raid_status(self, inter: discord.Interaction):
        raid = await self._active_raid(inter.guild_id)
        if not raid:
            return await inter.response.send_message("No active raid.", ephemeral=True)
        joined, done = await self._counts(raid["raid_id"])
        e = raid_embed(raid["title"], raid["tweet_url"], raid["ends_at"], joined, done)
        await inter.response.send_message(embed=e, ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="raid_end", description="End the current raid and show results.")
    @app_commands.default_permissions(manage_guild=True)
    async def raid_end(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)
        raid = await self._active_raid(inter.guild_id)
        if not raid:
            return await inter.followup.send("No active raid.", ephemeral=True)

        async with aiosqlite.connect(DB) as db:
            await db.execute("UPDATE raids SET active=0, ends_at=? WHERE raid_id=?", (int(time.time()), raid["raid_id"]))
            cur = await db.execute("""SELECT user_id, joined_at, done_at FROM raid_participants WHERE raid_id=? ORDER BY done_at ASC NULLS LAST""",
                                   (raid["raid_id"],))
            rows = await cur.fetchall(); await db.commit()

        # leaderboard (done users first by earliest done_at)
        done_rows = [r for r in rows if r[2]]
        lines = []
        for idx, (uid, _, done_at) in enumerate(done_rows, start=1):
            when = f"<t:{int(done_at)}:R>"
            lines.append(f"{idx}. <@{uid}> — {when}")

        if not lines:
            body = "No one marked done."
        else:
            body = "\n".join(lines[:20])  # show top 20

        ch = inter.guild.get_channel(raid["channel_id"]) or inter.channel
        res = discord.Embed(title=f"🏁 Raid Ended — {raid['title']}",
                            description=f"**Target:** {raid['tweet_url']}\n\n**Top Finishers:**\n{body}",
                            color=discord.Color.green())
        await ch.send(embed=res)
        await inter.followup.send("Raid ended.", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="raid_settings", description="Show raid settings.")
    async def raid_settings(self, inter: discord.Interaction):
        role_name = await self._get_set("RAID_ROLE_NAME", "Raiders")
        ch_id = await self._get_set("RAID_CHANNEL_ID", "—")
        default_min = await self._get_set("RAID_DEFAULT_MIN", "30")
        await inter.response.send_message(
            f"**Role:** {role_name}\n**Channel ID:** {ch_id}\n**Default Minutes:** {default_min}",
            ephemeral=True
        )

    @GUILD_DEC
    @app_commands.command(name="raid_set", description="Set a raid setting (admin).")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(key="RAID_ROLE_NAME | RAID_CHANNEL_ID | RAID_DEFAULT_MIN", value="New value")
    async def raid_set(self, inter: discord.Interaction, key: str, value: str):
        key = key.strip().upper()
        if key not in {"RAID_ROLE_NAME", "RAID_CHANNEL_ID", "RAID_DEFAULT_MIN"}:
            return await inter.response.send_message("Invalid key.", ephemeral=True)
        await self.settings.set(key, value)
        await inter.response.send_message(f"✅ `{key}` = `{value}`", ephemeral=True)

    # --- background: auto-end expired raids and refresh panel
    @tasks.loop(seconds=30)
    async def _ticker(self):
        try:
            now = int(time.time())
            async with aiosqlite.connect(DB) as db:
                cur = await db.execute("""SELECT raid_id,guild_id,channel_id,message_id,title,tweet_url,tweet_id,started_at,ends_at
                                          FROM raids WHERE active=1""")
                rows = await cur.fetchall()
            for (raid_id,guild_id,channel_id,message_id,title,tweet_url,tid,started,ends) in rows:
                guild = self.bot.get_guild(guild_id)
                if not guild: continue
                if ends and now >= ends:
                    # auto-end
                    try:
                        chan = guild.get_channel(channel_id)
                        if chan:
                            lb = discord.Embed(title=f"🏁 Raid Ended — {title}",
                                               description=f"**Target:** {tweet_url}\n(Auto-Ended)",
                                               color=discord.Color.green())
                            await chan.send(embed=lb)
                    except Exception:
                        pass
                    async with aiosqlite.connect(DB) as db:
                        await db.execute("UPDATE raids SET active=0 WHERE raid_id=?", (raid_id,))
                        await db.commit()
                    continue

                # refresh live panel counts
                try:
                    chan = guild.get_channel(channel_id)
                    if not chan or not message_id: continue
                    msg = await chan.fetch_message(message_id)
                    # counts
                    async with aiosqlite.connect(DB) as db:
                        cur = await db.execute("""SELECT COUNT(*), SUM(CASE WHEN done_at IS NOT NULL THEN 1 ELSE 0 END)
                                                 FROM raid_participants WHERE raid_id=?""", (raid_id,))
                        j, d = await cur.fetchone()
                    em = raid_embed(title, tweet_url, ends, int(j or 0), int(d or 0))
                    await msg.edit(embed=em, view=RaidView(tid, raid_id, ends))
                except Exception:
                    pass
        except Exception:
            pass

async def setup(bot):
    await bot.add_cog(Raids(bot))
