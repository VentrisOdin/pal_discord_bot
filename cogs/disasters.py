import os
import asyncio
import logging
import aiohttp
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, time as dtime
from dateutil import parser as dtparse

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.storage import Storage
from services.settings import Settings

USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
RELIEFWEB = "https://api.reliefweb.int/v1/reports"
EONET = "https://eonet.gsfc.nasa.gov/api/v3/events"
GDACS_RSS = "https://www.gdacs.org/xml/rss.xml"

_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DECORATOR = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

def emb(title, desc, url=None, fields=None):
    e = discord.Embed(title=title, description=desc)
    if url: e.url = url
    if fields:
        for n, v, i in fields: e.add_field(name=n, value=v, inline=i)
    e.set_footer(text="Auto-sourced • Disaster Watcher")
    return e

class Disasters(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.storage = Storage()
        self.settings = Settings()

        # runtime stats
        self._last_poll_dt: datetime | None = None
        self._last_poll_fetched: int = 0

        # session & buffers
        self._session: aiohttp.ClientSession | None = None
        self.digest_items: list[tuple[str, str, discord.Embed]] = []

        # default intervals; will be overridden by settings in runtime
        self.poll_disasters.change_interval(minutes=int(os.getenv("DISASTER_POLL_MINUTES", "5")))
        self.check_digest.change_interval(minutes=1)

    # ---------- lifecycle ----------
    async def cog_load(self):
        await self.storage.init()
        await self.settings.init()
        self._session = aiohttp.ClientSession()

        if not self.poll_disasters.is_running():
            self.poll_disasters.start()
            logging.info("Disasters: poll loop started (every %s min).",
                         await self._get_int_setting("DISASTER_POLL_MINUTES", 5))
        if not self.check_digest.is_running():
            self.check_digest.start()

    def cog_unload(self):
        if self.poll_disasters.is_running(): self.poll_disasters.cancel()
        if self.check_digest.is_running(): self.check_digest.cancel()
        if self._session and not self._session.closed:
            asyncio.create_task(self._session.close())

    # ---------- helpers / settings ----------
    async def _get_setting(self, key: str, default: str | None = None) -> str | None:
        return await self.settings.get(key, os.getenv(key) if default is None else default)

    async def _get_int_setting(self, key: str, default: int) -> int:
        val = await self._get_setting(key, str(default))
        try: return int(val) if val is not None else default
        except: return default

    async def _get_float_setting(self, key: str, default: float) -> float:
        val = await self._get_setting(key, str(default))
        try: return float(val) if val is not None else default
        except: return default

    def _channel(self, channel_id: int):
        return self.bot.get_channel(channel_id) if channel_id else None

    async def _post_embed(self, embed: discord.Embed, severe: bool = False):
        ch_id = int(await self._get_setting("DISASTER_CHANNEL_ID", "0") or 0)
        ch = self._channel(ch_id)
        if not ch: return
        role_name = await self._get_setting("ALERT_ROLE_NAME", "Disaster Alerts")
        role = discord.utils.get(ch.guild.roles, name=role_name) if role_name else None
        content = role.mention if (severe and role) else None
        await ch.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))

    # ---------- fetchers ----------
    async def fetch_usgs(self, min_mag: float):
        async with self._session.get(USGS_FEED, timeout=20) as r:
            data = await r.json()
        out = []
        for f in data.get("features", []):
            eid = f.get("id")
            p = f.get("properties", {})
            mag = float(p.get("mag") or 0.0)
            if mag < min_mag: continue
            place = p.get("place") or "Unknown location"
            tms = p.get("time")
            dt = datetime.fromtimestamp(tms/1000, tz=timezone.utc) if tms else None
            url = p.get("url")
            out.append(("usgs", eid, mag, emb(
                title=f"🌏 Earthquake M{mag:.1f} — {place}",
                desc=f"Time (UTC): {dt.isoformat() if dt else 'n/a'}\nSource: USGS",
                url=url,
                fields=[("Severity filter", f"M ≥ {min_mag:.1f}", True)]
            )))
        return out

    async def fetch_reliefweb(self, limit: int, appname: str):
        payload = {
            "appname": appname,
            "limit": limit,
            "profile": "full",
            "sort": ["date:desc"],
            "filter": {"operator":"AND","conditions":[
                {"field":"format","value":["Situation Report","Flash Update","Report"]},
                {"field":"date.created","range":{"from":"now-24h"}}
            ]},
            "fields":{"include":["title","url","date","source","country","disaster_type"]}
        }
        async with self._session.post(RELIEFWEB, json=payload, timeout=25) as r:
            data = await r.json()
        out = []
        for item in data.get("data", []):
            rid = str(item.get("id"))
            f = item.get("fields", {})
            title = f.get("title","ReliefWeb report")
            url = f.get("url")
            created = f.get("date",{}).get("created")
            dtv = dtparse.parse(created) if created else None
            countries = ", ".join([c["name"] for c in f.get("country", [])]) or "—"
            dtypes = ", ".join([t["name"] for t in f.get("disaster_type", [])]) or "—"
            srcs = ", ".join([s.get("shortname") or s.get("name") for s in f.get("source", [])]) or "ReliefWeb"
            out.append(("reliefweb", rid, None, emb(
                title=f"📰 {title}",
                desc=f"**Countries:** {countries}\n**Type:** {dtypes}\n**Published:** {dtv.isoformat() if dtv else 'n/a'}\n**Source(s):** {srcs}",
                url=url
            )))
        return out

    async def fetch_eonet(self):
        params = {"status":"open","limit":20}
        async with self._session.get(EONET, params=params, timeout=25) as r:
            data = await r.json()
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
            out.append(("eonet", eid, None, emb(
                title=f"🛰️ {title}",
                desc=f"**Category:** {cats}\n**Last update:** {dtv.isoformat() if dtv else 'n/a'}\nSource: NASA EONET",
                url=link
            )))
        return out

    async def fetch_gdacs(self):
        async with self._session.get(GDACS_RSS, timeout=25) as r:
            xml = await r.text()
        root = ET.fromstring(xml)
        out = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pubdate = item.findtext("pubDate")
            dtv = dtparse.parse(pubdate) if pubdate else None
            level = "Green"
            tl = title.lower()
            if "red alert" in tl: level = "Red"
            elif "orange alert" in tl: level = "Orange"
            if level not in ("Orange", "Red"):
                continue
            eid = link or title
            out.append(("gdacs", eid, level, emb(
                title=f"⚠️ GDACS {level} — {title}",
                desc=f"**Published:** {dtv.isoformat() if dtv else 'n/a'}\nSource: GDACS",
                url=link
            )))
        return out

    # ---------- posting ----------
    async def _handle_items(self, batch):
        mode = (await self._get_setting("DISASTER_MODE", "rt") or "rt").lower()
        ping_mag = await self._get_float_setting("USGS_PING_MAG", 6.8)
        if mode == "rt":
            for source, eid, sev, e in batch:
                if await self.storage.is_seen(source, eid): continue
                severe = False
                if source == "usgs":
                    severe = (sev or 0) >= ping_mag
                if source == "gdacs":
                    severe = (sev == "Red")
                await self._post_embed(e, severe=severe)
                await self.storage.mark_seen(source, eid)
        else:
            for source, eid, sev, e in batch:
                if await self.storage.is_seen(source, eid): continue
                self.digest_items.append((source, eid, e))

    # ---------- manual & status ----------
    @GUILD_DECORATOR
    @app_commands.command(name="disasters_now", description="Fetch and post the latest items now.")
    async def disasters_now(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            min_mag = await self._get_float_setting("USGS_MIN_MAG", 6.0)
            rw_limit = await self._get_int_setting("RELIEFWEB_LIMIT", 5)
            rw_app = await self._get_setting("RELIEFWEB_APPNAME", "pal-discord-bot")

            results = await asyncio.gather(
                self.fetch_usgs(min_mag),
                self.fetch_reliefweb(rw_limit, rw_app),
                self.fetch_eonet(),
                self.fetch_gdacs(),
                return_exceptions=True,
            )
            posted = 0
            for res in results:
                if isinstance(res, Exception):
                    logging.exception("Disasters: manual fetch error", exc_info=res)
                    continue
                for tup in res:
                    source, eid, sev, embed = tup
                    if not await self.storage.is_seen(source, eid):
                        await self._handle_items([tup])
                        posted += 1
            await interaction.followup.send(f"Triggered fetch. Posted {posted} new item(s).", ephemeral=True)
        except Exception as e:
            logging.exception("Disasters: /disasters_now failed", exc_info=e)
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @GUILD_DECORATOR
    @app_commands.command(name="status", description="Show disaster watcher status.")
    async def status(self, interaction: discord.Interaction):
        mode = await self._get_setting("DISASTER_MODE", "rt")
        ch_id = await self._get_setting("DISASTER_CHANNEL_ID", "—")
        min_mag = await self._get_setting("USGS_MIN_MAG", "6.0")
        ping_mag = await self._get_setting("USGS_PING_MAG", "6.8")
        last = self._last_poll_dt.isoformat() if self._last_poll_dt else "—"
        fetched = self._last_poll_fetched
        e = discord.Embed(title="🛰️ Disaster Watcher — Status")
        e.add_field(name="Mode", value=mode, inline=True)
        e.add_field(name="Channel ID", value=ch_id, inline=True)
        e.add_field(name="USGS Min Mag", value=min_mag, inline=True)
        e.add_field(name="USGS Ping Mag", value=ping_mag, inline=True)
        e.add_field(name="Last Poll UTC", value=last, inline=True)
        e.add_field(name="Last Poll Fetched", value=str(fetched), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ---------- loops ----------
    @tasks.loop(minutes=5, reconnect=True)
    async def poll_disasters(self):
        try:
            # refresh dynamic interval & channel every cycle
            interval = await self._get_int_setting("DISASTER_POLL_MINUTES", 5)
            if self.poll_disasters.seconds // 60 != interval:
                self.poll_disasters.change_interval(minutes=interval)

            min_mag = await self._get_float_setting("USGS_MIN_MAG", 6.0)
            rw_limit = await self._get_int_setting("RELIEFWEB_LIMIT", 5)
            rw_app = await self._get_setting("RELIEFWEB_APPNAME", "pal-discord-bot")

            logging.info("Disasters: polling sources...")
            results = await asyncio.gather(
                self.fetch_usgs(min_mag),
                self.fetch_reliefweb(rw_limit, rw_app),
                self.fetch_eonet(),
                self.fetch_gdacs(),
                return_exceptions=True,
            )
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

    @tasks.loop(minutes=1)
    async def check_digest(self):
        mode = (await self._get_setting("DISASTER_MODE", "rt") or "rt").lower()
        if mode != "digest": return
        # compute target each minute from settings
        tstr = await self._get_setting("DIGEST_TIME_UTC", "09:00")
        try:
            hh, mm = map(int, tstr.split(":"))
            target = dtime(hour=hh, minute=mm, tzinfo=timezone.utc)
        except Exception:
            target = dtime(hour=9, minute=0, tzinfo=timezone.utc)
        now = datetime.now(timezone.utc).time().replace(second=0, microsecond=0)
        if now == target and self.digest_items:
            ch_id = int(await self._get_setting("DISASTER_CHANNEL_ID", "0") or 0)
            ch = self._channel(ch_id)
            if not ch: return
            header = emb("🗞️ Daily Disaster Digest",
                         f"Collected updates until {datetime.now(timezone.utc).isoformat()}")
            await ch.send(embed=header)
            for source, eid, e in self.digest_items:
                await ch.send(embed=e)
                await self.storage.mark_seen(source, eid)
            self.digest_items.clear()

async def setup(bot: commands.Bot):
    await bot.add_cog(Disasters(bot))
