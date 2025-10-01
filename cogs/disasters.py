# cogs/disasters.py
import os
import asyncio
import logging
import aiohttp
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, time as dtime, timedelta
from dateutil import parser as dtparse

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.storage import Storage  # keep de-dupe across restarts

# ----- Hard-coded defaults (overridable by ENV) -----------------------------
DISASTER_CHANNEL_ID = int(os.getenv("DISASTER_CHANNEL_ID", "0") or 0)   # real-time posts
GENERAL_CHANNEL_ID  = int(os.getenv("GENERAL_CHANNEL_ID", "0") or 0)    # daily digest

DISASTER_POLL_MINUTES = int(os.getenv("DISASTER_POLL_MINUTES", "5") or 5)
DIGEST_TIME_UTC_STR   = os.getenv("DIGEST_TIME_UTC", "09:00")

ENABLE_USGS      = (os.getenv("ENABLE_USGS", "true").lower() in {"1","true","yes","on"})
ENABLE_RELIEFWEB = (os.getenv("ENABLE_RELIEFWEB", "true").lower() in {"1","true","yes","on"})
ENABLE_EONET     = (os.getenv("ENABLE_EONET", "true").lower() in {"1","true","yes","on"})
ENABLE_GDACS     = (os.getenv("ENABLE_GDACS", "true").lower() in {"1","true","yes","on"})

USGS_MIN_MAG = float(os.getenv("USGS_MIN_MAG", "5.0"))
USGS_PING_MAG = float(os.getenv("USGS_PING_MAG", "6.8"))  # mention role if >=
RELIEFWEB_LIMIT = int(os.getenv("RELIEFWEB_LIMIT", "5") or 5)
RELIEFWEB_APPNAME = os.getenv("RELIEFWEB_APPNAME", "pal-discord-bot")
ALERT_ROLE_NAME = os.getenv("ALERT_ROLE_NAME", "Disaster Alerts")  # ping on severe if present

# ----- Sources --------------------------------------------------------------
USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
RELIEFWEB = "https://api.reliefweb.int/v1/reports"
EONET     = "https://eonet.gsfc.nasa.gov/api/v3/events"
GDACS_RSS = "https://www.gdacs.org/xml/rss.xml"

# Slash scopes
_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

# Visual polish
COLORS = {
    "usgs": discord.Color.red(),
    "reliefweb": discord.Color.blurple(),
    "eonet": discord.Color.teal(),
    "gdacs": discord.Color.orange(),
}

def emb(title, desc, url=None, fields=None, source=None, ts: datetime | None = None):
    e = discord.Embed(title=title, description=desc, color=COLORS.get(source or "", discord.Color.dark_grey()))
    if url: e.url = url
    if fields:
        for n, v, i in fields:
            e.add_field(name=n, value=v, inline=i)
    if ts: e.timestamp = ts
    e.set_footer(text="Auto-sourced • Disaster Watcher")
    return e


class Disasters(commands.Cog):
    """
    Always-on behaviour:
      • Real-time: post every new item into DISASTER_CHANNEL_ID
      • Digest: at 09:00 UTC, post a summary into GENERAL_CHANNEL_ID
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.storage = Storage()
        self._session: aiohttp.ClientSession | None = None

        # runtime stats
        self._last_poll_dt: datetime | None = None
        self._last_poll_fetched: int = 0

        # digest buffers (reset daily after digest)
        self._digest_seen_today: set[tuple[str, str]] = set()
        self._digest_items: list[discord.Embed] = []
        self._last_digest_date: str | None = None  # 'YYYY-MM-DD'

        # schedule
        self.poll_disasters.change_interval(minutes=DISASTER_POLL_MINUTES)
        self.check_digest.change_interval(minutes=1)

    # ---------- lifecycle ----------
    async def cog_load(self):
        await self.storage.init()
        self._session = aiohttp.ClientSession(headers={"User-Agent": "Palaemon-DisasterBot/1.0 (+https://palaemon.vercel.app)"})

        if not self.poll_disasters.is_running():
            self.poll_disasters.start()
            logging.info("Disasters: poll loop started (every %s min).", DISASTER_POLL_MINUTES)
        if not self.check_digest.is_running():
            self.check_digest.start()
            logging.info("Disasters: digest checker started (every 1 min), target=%s UTC", DIGEST_TIME_UTC_STR)

    def cog_unload(self):
        if self.poll_disasters.is_running():
            self.poll_disasters.cancel()
        if self.check_digest.is_running():
            self.check_digest.cancel()
        if self._session and not self._session.closed:
            asyncio.create_task(self._session.close())

    # ---------- utilities ----------
    def _channel(self, channel_id: int):
        return self.bot.get_channel(channel_id) if channel_id else None

    async def _safe_send(self, channel: discord.TextChannel, *, content=None, embed: discord.Embed | None = None):
        try:
            await channel.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))
        except discord.Forbidden:
            logging.warning("Disasters: missing permissions to send in #%s (%s)", getattr(channel, "name", "?"), channel.id)
        except Exception as ex:
            logging.warning("Disasters: failed to post item: %s", ex)

    async def _post_realtime(self, embed: discord.Embed, severe: bool = False):
        ch = self._channel(DISASTER_CHANNEL_ID)
        if not ch:
            logging.warning("Disasters: DISASTER_CHANNEL_ID not set or not found.")
            return
        content = None
        if severe and ALERT_ROLE_NAME:
            role = discord.utils.get(ch.guild.roles, name=ALERT_ROLE_NAME)
            if role: content = role.mention
        await self._safe_send(ch, content=content, embed=embed)

    def _collect_for_digest(self, source: str, eid: str, embed: discord.Embed):
        key = (source, eid)
        if key in self._digest_seen_today:
            return
        self._digest_seen_today.add(key)
        self._digest_items.append(embed)

    # ---------- fetchers ----------
    async def fetch_usgs(self):
        if not ENABLE_USGS:
            return []
        try:
            async with self._session.get(USGS_FEED, timeout=20) as r:
                data = await r.json()
        except Exception as e:
            logging.exception("USGS fetch failed", exc_info=e)
            return []

        out = []
        for f in data.get("features", []):
            eid = f.get("id")
            p = f.get("properties", {})
            try:
                mag = float(p.get("mag") or 0.0)
            except:
                mag = 0.0
            if mag < USGS_MIN_MAG:
                continue
            place = p.get("place") or "Unknown location"
            tms = p.get("time")
            dt = datetime.fromtimestamp(tms / 1000, tz=timezone.utc) if tms else None
            url = p.get("url")
            out.append(
                ("usgs", eid, mag, emb(
                    title=f"🌏 Earthquake M{mag:.1f} — {place}",
                    desc=f"**Time (UTC):** {dt.isoformat() if dt else 'n/a'}\nSource: USGS",
                    url=url,
                    fields=[("Severity filter", f"M ≥ {USGS_MIN_MAG:.1f}", True)],
                    source="usgs",
                    ts=dt,
                ))
            )
        return out

    async def fetch_reliefweb(self):
        if not ENABLE_RELIEFWEB:
            return []
        payload = {
            "appname": RELIEFWEB_APPNAME,
            "limit": max(1, min(20, RELIEFWEB_LIMIT)),
            "profile": "full",
            "sort": ["date:desc"],
            "filter": {
                "operator": "AND",
                "conditions": [
                    {"field": "format", "value": ["Situation Report", "Flash Update", "Report"]},
                    {"field": "date.created", "range": {"from": "now-24h"}},
                ],
            },
            "fields": {"include": ["title", "url", "date", "source", "country", "disaster_type"]},
        }
        try:
            async with self._session.post(RELIEFWEB, json=payload, timeout=25) as r:
                data = await r.json()
        except Exception as e:
            logging.exception("ReliefWeb fetch failed", exc_info=e)
            return []

        out = []
        for item in data.get("data", []):
            rid = str(item.get("id"))
            f = item.get("fields", {})
            title = f.get("title", "ReliefWeb report")
            url = f.get("url")
            created = f.get("date", {}).get("created")
            dtv = dtparse.parse(created) if created else None
            countries = ", ".join([c["name"] for c in f.get("country", [])]) or "—"
            dtypes = ", ".join([t["name"] for t in f.get("disaster_type", [])]) or "—"
            srcs = ", ".join([s.get("shortname") or s.get("name") for s in f.get("source", [])]) or "ReliefWeb"
            out.append(
                ("reliefweb", rid, None, emb(
                    title=f"📰 {title}",
                    desc=(f"**Countries:** {countries}\n"
                          f"**Type:** {dtypes}\n"
                          f"**Published:** {dtv.isoformat() if dtv else 'n/a'}\n"
                          f"**Source(s):** {srcs}"),
                    url=url,
                    source="reliefweb",
                    ts=dtv,
                ))
            )
        return out

    async def fetch_eonet(self):
        if not ENABLE_EONET:
            return []
        params = {"status": "open", "limit": 20}
        try:
            async with self._session.get(EONET, params=params, timeout=25) as r:
                data = await r.json()
        except Exception as e:
            logging.exception("EONET fetch failed", exc_info=e)
            return []

        out = []
        for ev in data.get("events", []):
            eid = ev.get("id")
            title = ev.get("title")
            link = ev.get("link")
            cats = ", ".join([c["title"] for c in ev.get("categories", [])]) or "—"
            geo = ev.get("geometry", [])
            latest = geo[-1] if geo else {}
            when = latest.get("date")
            dtv = dtparse.parse(when) if when else None
            out.append(
                ("eonet", eid, None, emb(
                    title=f"🛰️ {title}",
                    desc=f"**Category:** {cats}\n**Last update:** {dtv.isoformat() if dtv else 'n/a'}\nSource: NASA EONET",
                    url=link,
                    source="eonet",
                    ts=dtv,
                ))
            )
        return out

    async def fetch_gdacs(self):
        if not ENABLE_GDACS:
            return []
        try:
            async with self._session.get(GDACS_RSS, timeout=25) as r:
                xml = await r.text()
        except Exception as e:
            logging.exception("GDACS fetch failed", exc_info=e)
            return []

        out = []
        try:
            root = ET.fromstring(xml)
        except Exception:
            logging.warning("GDACS RSS parse error")
            return out

        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pubdate = item.findtext("pubDate")
            dtv = dtparse.parse(pubdate) if pubdate else None
            level = "Green"
            tl = title.lower()
            if "red alert" in tl:
                level = "Red"
            elif "orange alert" in tl:
                level = "Orange"
            if level not in ("Orange", "Red"):
                continue
            eid = link or title
            out.append(
                ("gdacs", eid, level, emb(
                    title=f"⚠️ GDACS {level} — {title}",
                    desc=f"**Published:** {dtv.isoformat() if dtv else 'n/a'}\nSource: GDACS",
                    url=link,
                    source="gdacs",
                    ts=dtv,
                ))
            )
        return out

    # ---------- posting pipeline ----------
    async def _handle_items(self, batch):
        for source, eid, sev, e in batch:
            # de-dupe globally
            if await self.storage.is_seen(source, eid):
                continue

            # realtime post
            severe = False
            if source == "usgs":
                severe = (sev or 0) >= USGS_PING_MAG
            if source == "gdacs":
                severe = (sev == "Red")

            await self._post_realtime(e, severe=severe)

            # collect for digest
            self._collect_for_digest(source, eid, e)

            # mark seen so we don't re-post
            await self.storage.mark_seen(source, eid)

    # ---------- manual/status ----------
    @GUILD_DEC
    @app_commands.command(name="disasters_now", description="Fetch and post the latest items now.")
    async def disasters_now(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            calls = []
            if ENABLE_USGS:      calls.append(self.fetch_usgs())
            if ENABLE_RELIEFWEB: calls.append(self.fetch_reliefweb())
            if ENABLE_EONET:     calls.append(self.fetch_eonet())
            if ENABLE_GDACS:     calls.append(self.fetch_gdacs())

            results = await asyncio.gather(*calls, return_exceptions=True)
            posted = 0
            for res in results:
                if isinstance(res, Exception):
                    logging.exception("Disasters: manual fetch error", exc_info=res)
                    continue
                await self._handle_items(res)
                posted += sum(1 for _ in res)
            await interaction.followup.send(f"Triggered fetch. Processed {posted} item(s).", ephemeral=True)
        except Exception as e:
            logging.exception("Disasters: /disasters_now failed", exc_info=e)
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="status", description="Show disaster watcher status.")
    async def status(self, interaction: discord.Interaction):
        e = discord.Embed(title="🛰️ Disaster Watcher — Status", color=discord.Color.greyple())
        e.add_field(name="Realtime Channel", value=str(DISASTER_CHANNEL_ID), inline=True)
        e.add_field(name="Digest Channel", value=str(GENERAL_CHANNEL_ID), inline=True)
        e.add_field(name="Poll Interval", value=f"{DISASTER_POLL_MINUTES} min", inline=True)
        e.add_field(name="Digest Time (UTC)", value=DIGEST_TIME_UTC_STR, inline=True)
        e.add_field(name="USGS Min/Ping", value=f"{USGS_MIN_MAG}/{USGS_PING_MAG}", inline=True)
        e.add_field(name="Sources", value=f"USGS:{ENABLE_USGS} RW:{ENABLE_RELIEFWEB} EONET:{ENABLE_EONET} GDACS:{ENABLE_GDACS}", inline=False)
        e.add_field(name="Last Poll UTC", value=(self._last_poll_dt.isoformat() if self._last_poll_dt else "—"), inline=True)
        e.add_field(name="Last Poll Fetched", value=str(self._last_poll_fetched), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ---------- loops ----------
    @tasks.loop(minutes=DISASTER_POLL_MINUTES, reconnect=True)
    async def poll_disasters(self):
        try:
            logging.info("Disasters: polling sources...")
            calls = []
            if ENABLE_USGS:      calls.append(self.fetch_usgs())
            if ENABLE_RELIEFWEB: calls.append(self.fetch_reliefweb())
            if ENABLE_EONET:     calls.append(self.fetch_eonet())
            if ENABLE_GDACS:     calls.append(self.fetch_gdacs())

            results = await asyncio.gather(*calls, return_exceptions=True)

            fetched = 0
            for res in results:
                if isinstance(res, Exception):
                    logging.exception("Disasters: fetch error", exc_info=res)
                    continue
                await self._handle_items(res)
                fetched += len(res)

            self._last_poll_dt = datetime.now(timezone.utc)
            self._last_poll_fetched = fetched
            logging.info("Disasters: poll complete — %s items (pre de-dupe).", fetched)
        except Exception as e:
            logging.exception("Disasters: poll loop error", exc_info=e)

    @poll_disasters.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def check_digest(self):
        try:
            # parse target UTC time
            try:
                hh, mm = map(int, DIGEST_TIME_UTC_STR.split(":"))
                target = dtime(hour=hh, minute=mm, tzinfo=timezone.utc)
            except Exception:
                target = dtime(hour=9, minute=0, tzinfo=timezone.utc)

            now_dt = datetime.now(timezone.utc)
            today_key = now_dt.strftime("%Y-%m-%d")

            # Already posted today?
            if self._last_digest_date == today_key:
                return

            # 90s window to avoid drift
            target_dt = datetime.combine(now_dt.date(), target)
            if abs((now_dt - target_dt).total_seconds()) > 90:
                return

            if not self._digest_items:
                logging.info("Disasters: digest window hit, but no items collected.")
                self._last_digest_date = today_key
                return

            ch = self._channel(GENERAL_CHANNEL_ID)
            if not ch:
                logging.warning("Disasters: GENERAL_CHANNEL_ID not set or not found for digest.")
                return

            header = emb(
                "🗞️ Daily Disaster Digest",
                f"Collected updates until {now_dt.isoformat()}",
                source="reliefweb",
                ts=now_dt,
            )
            await self._safe_send(ch, embed=header)

            for e in self._digest_items:
                await self._safe_send(ch, embed=e)

            self._digest_items.clear()
            self._digest_seen_today.clear()
            self._last_digest_date = today_key
            logging.info("Disasters: posted daily digest.")
        except Exception as e:
            logging.exception("Disasters: check_digest error", exc_info=e)

    @check_digest.before_loop
    async def before_digest(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(Disasters(bot))
