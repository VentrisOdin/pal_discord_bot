# cogs/disasters.py
import os
import io
import csv
import json
import asyncio
import logging
import aiohttp
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, time as dtime
from dateutil import parser as dtparse

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.storage import Storage           # de-dupe across restarts
from services.settings import Settings         # live toggles & thresholds

# -------------------- Constants / Defaults (env fallbacks) --------------------

USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
RELIEFWEB_REPORTS = "https://api.reliefweb.int/v1/reports"
RELIEFWEB_DISASTERS = "https://api.reliefweb.int/v1/disasters"
EONET = "https://eonet.gsfc.nasa.gov/api/v3/events"
GDACS_RSS = "https://www.gdacs.org/xml/rss.xml"
GDACS_JSON = "https://www.gdacs.org/gdacsapi/api/events/geteventlist"  # basic list (no params)
WHO_DON_RSS = "https://www.who.int/feeds/entity/csr/don/en/rss.xml"
COPERNICUS_RSS = "https://emergency.copernicus.eu/mapping/list-of-components/EMSR/rss.xml"
NWS_ALERTS = "https://api.weather.gov/alerts/active?status=actual"
NHC_RSS    = "https://www.nhc.noaa.gov/nhc_at.xml"
PTWC_RSS   = "https://www.tsunami.gov/events/xml/atom"
GVP_RSS    = "https://volcano.si.edu/news/WeeklyVolcanoRSS.xml"
FLOODLIST  = "https://floodlist.com/feed"

# Slash scopes
_GUILD_ID_RAW = os.getenv("GUILD_ID") or ""
GUILD_ID = int(_GUILD_ID_RAW) if _GUILD_ID_RAW.isdigit() else None
GUILD_DEC = app_commands.guilds(GUILD_ID) if GUILD_ID else (lambda f: f)

COLORS = {
    "usgs": discord.Color.red(),
    "reliefweb": discord.Color.blurple(),
    "reliefweb_dis": discord.Color.dark_teal(),
    "eonet": discord.Color.teal(),
    "gdacs": discord.Color.orange(),
    "gdacs_json": discord.Color.orange(),
    "who": discord.Color.dark_orange(),
    "copernicus": discord.Color.dark_blue(),
    "firms": discord.Color.dark_magenta(),
    # Add these new ones:
    "nws": discord.Color.gold(),
    "nhc": discord.Color.dark_orange(),
    "ptwc": discord.Color.dark_teal(),
    "gvp": discord.Color.dark_red(),
    "floodlist": discord.Color.dark_green(),
}

def emb(title, desc, url=None, fields=None, source=None, ts: datetime | None = None):
    e = discord.Embed(title=title, description=desc, color=COLORS.get(source or "", discord.Color.dark_grey()))
    if url:
        e.url = url
    if fields:
        for n, v, i in fields:
            e.add_field(name=n, value=v, inline=i)
    if ts:
        e.timestamp = ts
    e.set_footer(text="Auto-sourced • Disaster Watcher")
    return e


class Disasters(commands.Cog):
    """
    Real-time posts → DISASTER_CHANNEL_ID
    Daily digest at DIGEST_TIME_UTC → GENERAL_CHANNEL_ID
    All behavior is live-tunable via /sources_* and Settings().
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.storage = Storage()
        self.settings = Settings()
        self._session: aiohttp.ClientSession | None = None

        # runtime stats
        self._last_poll_dt: datetime | None = None
        self._last_poll_fetched: int = 0

        # digest buffers (reset after daily digest)
        self._digest_seen_today: set[tuple[str, str]] = set()
        self._digest_items: list[discord.Embed] = []
        self._last_digest_date: str | None = None  # 'YYYY-MM-DD'

        # schedule (placeholder; real intervals pulled dynamically each tick)
        self.poll_disasters.change_interval(minutes=int(os.getenv("DISASTER_POLL_MINUTES", "5")))
        self.check_digest.change_interval(minutes=1)

    # -------------------- lifecycle --------------------

    async def cog_load(self):
        await self.storage.init()
        await self.settings.init()
        self._session = aiohttp.ClientSession(headers={"User-Agent": "Palaemon-DisasterBot/1.0 (+https://palaemon.vercel.app)"})

        if not self.poll_disasters.is_running():
            self.poll_disasters.start()
            logging.info("Disasters: poll loop started.")
        if not self.check_digest.is_running():
            self.check_digest.start()
            logging.info("Disasters: digest checker started (every 1 min).")

    def cog_unload(self):
        if self.poll_disasters.is_running():
            self.poll_disasters.cancel()
        if self.check_digest.is_running():
            self.check_digest.cancel()
        if self._session and not self._session.closed:
            asyncio.create_task(self._session.close())

    # -------------------- setting helpers (DB with env fallback) --------------------

    async def _get(self, key: str, default_env: str | None = None) -> str | None:
        return await self.settings.get(key, os.getenv(key) if default_env is None else default_env)

    async def _get_bool(self, key: str, default: bool) -> bool:
        val = await self._get(key, "true" if default else "false")
        s = (val or "").strip().lower()
        return s in {"1", "true", "yes", "y", "on"}

    async def _get_int(self, key: str, default: int) -> int:
        val = await self._get(key, str(default))
        try:
            return int(val) if val is not None else default
        except:
            return default

    async def _get_float(self, key: str, default: float) -> float:
        val = await self._get(key, str(default))
        try:
            return float(val) if val is not None else default
        except:
            return default

    # -------------------- utilities --------------------

    def _channel(self, channel_id: int):
        return self.bot.get_channel(channel_id) if channel_id else None

    async def _safe_send(self, channel: discord.TextChannel, *, content=None, embed: discord.Embed | None = None):
        try:
            await channel.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True))
        except discord.Forbidden:
            logging.warning("Disasters: missing permissions to send in #%s (%s)", getattr(channel, "name", "?"), channel.id)
        except Exception as ex:
            logging.warning("Disasters: failed to post item: %s", ex)

    async def _post_realtime(self, embed: discord.Embed, severe: bool, alert_role_name: str | None, channel_id: int):
        ch = self._channel(channel_id)
        if not ch:
            logging.warning("Disasters: realtime channel not set/found (id=%s).", channel_id)
            return
        content = None
        if severe and alert_role_name:
            role = discord.utils.get(ch.guild.roles, name=alert_role_name)
            if role:
                content = role.mention
        await self._safe_send(ch, content=content, embed=embed)

    def _collect_for_digest(self, source: str, eid: str, embed: discord.Embed):
        key = (source, eid)
        if key in self._digest_seen_today:
            return
        self._digest_seen_today.add(key)
        self._digest_items.append(embed)

    # -------------------- fetchers (each returns list[(source, id, sev, embed)]) --------------------

    async def fetch_usgs(self, min_mag: float):
        try:
            async with self._session.get(USGS_FEED, timeout=20) as r:
                data = await r.json()
        except Exception as e:
            logging.exception("USGS fetch failed", exc_info=e)
            return []

        out = []
        for f in data.get("features", []):
            eid = f.get("id")
            p = f.get("properties", {}) or {}
            try:
                mag = float(p.get("mag") or 0.0)
            except:
                mag = 0.0
            if mag < min_mag:
                continue
            place = p.get("place") or "Unknown location"
            tms = p.get("time")
            dt = datetime.fromtimestamp(tms / 1000, tz=timezone.utc) if tms else None
            url = p.get("url")
            out.append(("usgs", eid, mag, emb(
                title=f"🌏 Earthquake M{mag:.1f} — {place}",
                desc=f"**Time (UTC):** {dt.isoformat() if dt else 'n/a'}\nSource: USGS",
                url=url,
                fields=[("Severity filter", f"M ≥ {min_mag:.1f}", True)],
                source="usgs",
                ts=dt,
            )))
        return out

    async def fetch_reliefweb_reports(self, limit: int, appname: str):
        payload = {
            "appname": appname,
            "limit": max(1, min(20, limit)),
            "profile": "full",
            "sort": ["date:desc"],
            "filter": {"operator": "AND", "conditions": [
                {"field": "format", "value": ["Situation Report", "Flash Update", "Report"]},
                {"field": "date.created", "range": {"from": "now-24h"}}
            ]},
            "fields": {"include": ["title", "url", "date", "source", "country", "disaster_type"]}
        }
        try:
            async with self._session.post(RELIEFWEB_REPORTS, json=payload, timeout=25) as r:
                data = await r.json()
        except Exception as e:
            logging.exception("ReliefWeb reports fetch failed", exc_info=e)
            return []

        out = []
        for item in data.get("data", []):
            rid = str(item.get("id"))
            f = item.get("fields", {}) or {}
            title = f.get("title", "ReliefWeb report")
            url = f.get("url")
            created = (f.get("date") or {}).get("created")
            dtv = dtparse.parse(created) if created else None
            countries = ", ".join([c["name"] for c in f.get("country", [])]) or "—"
            dtypes = ", ".join([t["name"] for t in f.get("disaster_type", [])]) or "—"
            srcs = ", ".join([(s.get("shortname") or s.get("name")) for s in f.get("source", [])]) or "ReliefWeb"
            out.append(("reliefweb", rid, None, emb(
                title=f"📰 {title}",
                desc=(f"**Countries:** {countries}\n"
                      f"**Type:** {dtypes}\n"
                      f"**Published:** {dtv.isoformat() if dtv else 'n/a'}\n"
                      f"**Source(s):** {srcs}"),
                url=url,
                source="reliefweb",
                ts=dtv,
            )))
        return out

    async def fetch_reliefweb_disasters(self, limit: int, appname: str):
        payload = {
            "appname": appname,
            "limit": max(1, min(20, limit)),
            "profile": "full",
            "sort": ["date:desc"],
            "filter": {"operator": "AND", "conditions": [
                {"field": "date.created", "range": {"from": "now-24h"}}
            ]},
            "fields": {"include": ["name", "primary_type", "date", "url", "country", "status"]}
        }
        try:
            async with self._session.post(RELIEFWEB_DISASTERS, json=payload, timeout=25) as r:
                data = await r.json()
        except Exception as e:
            logging.exception("ReliefWeb disasters fetch failed", exc_info=e)
            return []

        out = []
        for item in data.get("data", []):
            did = str(item.get("id"))
            f = item.get("fields", {}) or {}
            title = f.get("name", "Disaster")
            url = f.get("url")
            created = (f.get("date") or {}).get("created")
            dtv = dtparse.parse(created) if created else None
            countries = ", ".join([c["name"] for c in f.get("country", [])]) or "—"
            dtype = (f.get("primary_type") or {}).get("name", "—")
            status = f.get("status", "—")
            out.append(("reliefweb_dis", did, None, emb(
                title=f"🧭 {title}",
                desc=(f"**Type:** {dtype}\n"
                      f"**Countries:** {countries}\n"
                      f"**Status:** {status}\n"
                      f"**Created:** {dtv.isoformat() if dtv else 'n/a'}"),
                url=url,
                source="reliefweb_dis",
                ts=dtv,
            )))
        return out

    async def fetch_eonet(self):
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
            out.append(("eonet", eid, None, emb(
                title=f"🛰️ {title}",
                desc=f"**Category:** {cats}\n**Last update:** {dtv.isoformat() if dtv else 'n/a'}\nSource: NASA EONET",
                url=link,
                source="eonet",
                ts=dtv,
            )))
        return out

    async def fetch_gdacs_rss(self):
        try:
            async with self._session.get(GDACS_RSS, timeout=25) as r:
                xml = await r.text()
        except Exception as e:
            logging.exception("GDACS RSS fetch failed", exc_info=e)
            return []
        try:
            root = ET.fromstring(xml)
        except Exception:
            logging.warning("GDACS RSS parse error")
            return []
        out = []
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
            out.append(("gdacs", eid, level, emb(
                title=f"⚠️ GDACS {level} — {title}",
                desc=f"**Published:** {dtv.isoformat() if dtv else 'n/a'}\nSource: GDACS",
                url=link,
                source="gdacs",
                ts=dtv,
            )))
        return out

    async def fetch_gdacs_json(self):
        try:
            async with self._session.get(GDACS_JSON, timeout=25) as r:
                data = await r.json()
        except Exception as e:
            logging.exception("GDACS JSON fetch failed", exc_info=e)
            return []
        events = data if isinstance(data, list) else data.get("features") or []
        out = []
        for ev in events:
            # GDACS JSON formats vary; try both flat and geojson-ish
            if isinstance(ev, dict) and "eventid" in ev:
                eid = str(ev.get("eventid"))
                title = ev.get("eventname") or f"{ev.get('eventtype', 'Event')} {eid}"
                level = (ev.get("alertlevel") or "").capitalize()  # Red/Orange/Green
                link = ev.get("eventurl") or ev.get("url") or "https://www.gdacs.org/"
                if level not in ("Orange", "Red"):
                    continue
                out.append(("gdacs_json", eid, level, emb(
                    title=f"⚠️ GDACS {level} — {title}",
                    desc=f"Source: GDACS (JSON)",
                    url=link,
                    source="gdacs_json",
                    ts=None,
                )))
            elif isinstance(ev, dict) and "properties" in ev:
                p = ev["properties"]
                eid = str(p.get("eventid") or p.get("id") or p.get("name"))
                title = p.get("eventname") or p.get("title") or "GDACS Event"
                level = (p.get("alertlevel") or "").capitalize()
                link = p.get("url") or "https://www.gdacs.org/"
                if level not in ("Orange", "Red"):
                    continue
                out.append(("gdacs_json", eid, level, emb(
                    title=f"⚠️ GDACS {level} — {title}",
                    desc=f"Source: GDACS (JSON)",
                    url=link,
                    source="gdacs_json",
                    ts=None,
                )))
        return out

    async def fetch_who_don(self):
        try:
            async with self._session.get(WHO_DON_RSS, timeout=25) as r:
                xml = await r.text()
        except Exception as e:
            logging.exception("WHO DON fetch failed", exc_info=e)
            return []
        try:
            root = ET.fromstring(xml)
        except Exception:
            logging.warning("WHO DON RSS parse error")
            return []
        out = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pubdate = item.findtext("pubDate")
            dtv = dtparse.parse(pubdate) if pubdate else None
            eid = link or title
            out.append(("who", eid, None, emb(
                title=f"🧬 WHO Disease Outbreak — {title}",
                desc=f"**Published:** {dtv.isoformat() if dtv else 'n/a'}\nSource: WHO DON",
                url=link,
                source="who",
                ts=dtv,
            )))
        return out

    async def fetch_copernicus(self):
        try:
            async with self._session.get(COPERNICUS_RSS, timeout=25) as r:
                xml = await r.text()
        except Exception as e:
            logging.exception("Copernicus RSS fetch failed", exc_info=e)
            return []
        try:
            root = ET.fromstring(xml)
        except Exception:
            logging.warning("Copernicus RSS parse error")
            return []
        out = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pubdate = item.findtext("pubDate")
            dtv = dtparse.parse(pubdate) if pubdate else None
            eid = link or title
            out.append(("copernicus", eid, None, emb(
                title=f"🛰️ Copernicus EMS — {title}",
                desc=f"**Published:** {dtv.isoformat() if dtv else 'n/a'}\nSource: Copernicus EMS",
                url=link,
                source="copernicus",
                ts=dtv,
            )))
        return out

    async def fetch_firms(self, firms_url: str):
        if not firms_url:
            return []
        try:
            async with self._session.get(firms_url, timeout=25) as r:
                content_type = (r.headers.get("Content-Type") or "").lower()
                data = await r.read()
        except Exception as e:
            logging.exception("FIRMS fetch failed", exc_info=e)
            return []

        out = []
        try:
            if "application/json" in content_type or firms_url.lower().endswith((".json", ".geojson")):
                j = json.loads(data.decode("utf-8", errors="ignore"))
                features = j.get("features", [])
                for feat in features[:50]:  # keep it sensible
                    props = feat.get("properties", {}) or {}
                    eid = str(props.get("id") or props.get("bright_ti4") or props.get("frp") or hash(str(props)))
                    lat = props.get("latitude") or props.get("LATITUDE") or props.get("lat") or "?"
                    lon = props.get("longitude") or props.get("LONGITUDE") or props.get("lon") or "?"
                    acq = props.get("acq_date") or props.get("Date") or props.get("date")
                    dtv = dtparse.parse(acq) if acq else None
                    out.append(("firms", eid, None, emb(
                        title="🔥 FIRMS Active Fire",
                        desc=f"**Lat/Lon:** {lat}, {lon}\n**Acquired:** {dtv.isoformat() if dtv else 'n/a'}",
                        url=firms_url,
                        source="firms",
                        ts=dtv,
                    )))
            else:
                # CSV fallback (NASA public downloads often CSV)
                text = data.decode("utf-8", errors="ignore")
                reader = csv.DictReader(io.StringIO(text))
                for i, row in enumerate(reader):
                    if i >= 50:
                        break
                    eid = row.get("id") or row.get("BRIGHT_TI4") or row.get("FRP") or f"row-{i}"
                    lat = row.get("latitude") or row.get("LATITUDE") or row.get("lat") or "?"
                    lon = row.get("longitude") or row.get("LONGITUDE") or row.get("lon") or "?"
                    acq = row.get("acq_date") or row.get("Date") or row.get("date")
                    dtv = dtparse.parse(acq) if acq else None
                    out.append(("firms", str(eid), None, emb(
                        title="🔥 FIRMS Active Fire",
                        desc=f"**Lat/Lon:** {lat}, {lon}\n**Acquired:** {dtv.isoformat() if dtv else 'n/a'}",
                        url=firms_url,
                        source="firms",
                        ts=dtv,
                    )))
        except Exception as e:
            logging.exception("FIRMS parse failed", exc_info=e)
        return out

    async def fetch_nws(self):
        """USA severe weather alerts from NWS (JSON)."""
        try:
            async with self._session.get(NWS_ALERTS, timeout=25) as r:
                data = await r.json()
        except Exception as e:
            logging.exception("NWS fetch failed", exc_info=e)
            return []

        out = []
        for feat in data.get("features", []):
            props = feat.get("properties", {}) or {}
            eid = props.get("id") or feat.get("id") or props.get("event") or "nws-unknown"
            event = props.get("event") or "NWS Alert"
            severity = props.get("severity") or "Unknown"
            area = props.get("areaDesc") or "—"
            headline = props.get("headline") or ""
            uri = props.get("uri") or props.get("url") or "https://www.weather.gov/"

            eff = props.get("effective") or props.get("onset") or props.get("sent")
            dtv = dtparse.parse(eff) if eff else None

            desc = (f"**Event:** {event}\n"
                    f"**Severity:** {severity}\n"
                    f"**Area:** {area}\n"
                    f"{headline}")
            out.append(("nws", str(eid), severity, emb(
                title=f"⛑️ NWS Alert — {event}",
                desc=desc,
                url=uri,
                source="nws",
                ts=dtv,
            )))
        return out

    async def fetch_nhc(self):
        """NOAA/NHC Atlantic tropical advisories (RSS)."""
        try:
            async with self._session.get(NHC_RSS, timeout=25) as r:
                xml = await r.text(encoding='utf-8', errors='ignore')
            root = ET.fromstring(xml)
        except Exception as e:
            logging.exception("NHC fetch failed", exc_info=e)
            return []

        out = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pubdate = item.findtext("pubDate")
            dtv = dtparse.parse(pubdate) if pubdate else None
            eid = link or title
            out.append(("nhc", eid, None, emb(
                title=f"🌀 NHC Advisory — {title}",
                desc=f"**Published:** {dtv.isoformat() if dtv else 'n/a'}\nSource: NOAA/NHC",
                url=link,
                source="nhc",
                ts=dtv,
            )))
        return out

    async def fetch_ptwc(self):
        """PTWC tsunami alerts (Atom)."""
        try:
            async with self._session.get(PTWC_RSS, timeout=25) as r:
                xml = await r.text(encoding='utf-8', errors='ignore')
            root = ET.fromstring(xml)
        except Exception as e:
            logging.exception("PTWC fetch failed", exc_info=e)
            return []

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall(".//atom:entry", ns) or root.findall(".//entry")
        out = []
        for ent in entries:
            title = (ent.findtext("atom:title", default="", namespaces=ns) or ent.findtext("title") or "").strip()
            link_el = ent.find("atom:link", ns) or ent.find("link")
            link = (link_el.get("href") if link_el is not None else "") or ""
            updated = ent.findtext("atom:updated", default="", namespaces=ns) or ent.findtext("updated")
            dtv = dtparse.parse(updated) if updated else None
            eid = link or title
            out.append(("ptwc", eid, None, emb(
                title=f"🌊 PTWC — {title}",
                desc=f"**Updated:** {dtv.isoformat() if dtv else 'n/a'}\nSource: PTWC",
                url=link or "https://www.tsunami.gov/",
                source="ptwc",
                ts=dtv,
            )))
        return out

    async def fetch_gvp(self):
        """Smithsonian Global Volcanism Program weekly digest (RSS)."""
        try:
            async with self._session.get(GVP_RSS, timeout=25) as r:
                xml = await r.text(encoding='utf-8', errors='ignore')
            root = ET.fromstring(xml)
        except Exception as e:
            logging.exception("GVP fetch failed", exc_info=e)
            return []

        out = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pubdate = item.findtext("pubDate")
            dtv = dtparse.parse(pubdate) if pubdate else None
            eid = link or title
            out.append(("gvp", eid, None, emb(
                title=f"🌋 Volcano Activity — {title}",
                desc=f"**Published:** {dtv.isoformat() if dtv else 'n/a'}\nSource: Smithsonian GVP",
                url=link,
                source="gvp",
                ts=dtv,
            )))
        return out

    async def fetch_floodlist(self):
        """FloodList global flood events (RSS)."""
        try:
            async with self._session.get(FLOODLIST, timeout=25) as r:
                xml = await r.text(encoding='utf-8', errors='ignore')
            root = ET.fromstring(xml)
        except Exception as e:
            logging.exception("FloodList fetch failed", exc_info=e)
            return []

        out = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pubdate = item.findtext("pubDate")
            dtv = dtparse.parse(pubdate) if pubdate else None
            eid = link or title
            out.append(("floodlist", eid, None, emb(
                title=f"🌧️ Floods — {title}",
                desc=f"**Published:** {dtv.isoformat() if dtv else 'n/a'}\nSource: FloodList",
                url=link,
                source="floodlist",
                ts=dtv,
            )))
        return out
    # -------------------- pipeline --------------------

    async def _handle_items(self, batch, alert_role_name: str, ping_mag: float, rt_channel_id: int):
        for source, eid, sev, e in batch:
            if await self.storage.is_seen(source, eid):
                continue
            severe = False
            if source == "usgs":
                severe = (sev or 0) >= ping_mag
            elif source in ("gdacs", "gdacs_json"):
                severe = (sev == "Red")
            elif source == "nws" and isinstance(sev, str):
                severe = sev.lower() in {"extreme", "severe"}
            elif source == "ptwc":
                severe = True  # tsunami alerts are always ping-worthy
            elif source == "nhc":
                severe = "warning" in e.title.lower() or "watch" in e.title.lower()
            await self._post_realtime(e, severe=severe, alert_role_name=alert_role_name, channel_id=rt_channel_id)
            self._collect_for_digest(source, eid, e)
            await self.storage.mark_seen(source, eid)

    # -------------------- slash: manual / status --------------------

    @GUILD_DEC
    @app_commands.command(name="disasters_now", description="Fetch and post the latest items now.")
    async def disasters_now(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=True)

        # read current config
        rt_channel_id = await self._get_int("DISASTER_CHANNEL_ID", int(os.getenv("DISASTER_CHANNEL_ID", "0") or 0))
        alert_role = await self._get("ALERT_ROLE_NAME", os.getenv("ALERT_ROLE_NAME", "Disaster Alerts"))
        min_mag = await self._get_float("USGS_MIN_MAG", float(os.getenv("USGS_MIN_MAG", "5.0")))
        ping_mag = await self._get_float("USGS_PING_MAG", float(os.getenv("USGS_PING_MAG", "6.8")))
        rw_limit = await self._get_int("RELIEFWEB_LIMIT", int(os.getenv("RELIEFWEB_LIMIT", "5") or 5))
        rw_app = await self._get("RELIEFWEB_APPNAME", os.getenv("RELIEFWEB_APPNAME", "pal-discord-bot"))
        firms_url = await self._get("FIRMS_URL", os.getenv("FIRMS_URL", ""))

        use = {
            "usgs": await self._get_bool("ENABLE_USGS", True),
            "rw_reports": await self._get_bool("ENABLE_RELIEFWEB", True),
            "rw_dis": await self._get_bool("ENABLE_RW_DISASTERS", False),
            "eonet": await self._get_bool("ENABLE_EONET", True),
            "gdacs_json": await self._get_bool("ENABLE_GDACS_JSON", True),
            "gdacs": await self._get_bool("ENABLE_GDACS", True),
            "who": await self._get_bool("ENABLE_WHO", True),
            "copernicus": await self._get_bool("ENABLE_COPERNICUS", True),
            "firms": await self._get_bool("ENABLE_FIRMS", False),
            # Add these new ones:
            "nws": await self._get_bool("ENABLE_NWS", False),
            "nhc": await self._get_bool("ENABLE_NHC", True),
            "ptwc": await self._get_bool("ENABLE_PTWC", True),
            "gvp": await self._get_bool("ENABLE_GVP", True),
            "floodlist": await self._get_bool("ENABLE_FLOODLIST", True),
        }

        calls = []
        if use["usgs"]:         calls.append(self.fetch_usgs(min_mag))
        if use["rw_reports"]:   calls.append(self.fetch_reliefweb_reports(rw_limit, rw_app))
        if use["rw_dis"]:       calls.append(self.fetch_reliefweb_disasters(rw_limit, rw_app))
        if use["eonet"]:        calls.append(self.fetch_eonet())
        if use["gdacs_json"]:   calls.append(self.fetch_gdacs_json())
        if use["gdacs"]:        calls.append(self.fetch_gdacs_rss())
        if use["who"]:          calls.append(self.fetch_who_don())
        if use["copernicus"]:   calls.append(self.fetch_copernicus())
        if use["firms"] and firms_url: calls.append(self.fetch_firms(firms_url))
        # Add these new fetchers:
        if use["nws"]:          calls.append(self.fetch_nws())
        if use["nhc"]:          calls.append(self.fetch_nhc())
        if use["ptwc"]:         calls.append(self.fetch_ptwc())
        if use["gvp"]:          calls.append(self.fetch_gvp())
        if use["floodlist"]:    calls.append(self.fetch_floodlist())

        results = await asyncio.gather(*calls, return_exceptions=True)
        posted = 0
        for res in results:
            if isinstance(res, Exception):
                logging.exception("Disasters: manual fetch error", exc_info=res)
                continue
            await self._handle_items(res, alert_role_name=alert_role, ping_mag=ping_mag, rt_channel_id=rt_channel_id)
            posted += len(res)

        await inter.followup.send(f"Triggered fetch. Processed {posted} item(s).", ephemeral=True)

    @GUILD_DEC
    @app_commands.command(name="status", description="Show disaster watcher status.")
    async def status(self, interaction: discord.Interaction):
        rt_channel_id = await self._get_int("DISASTER_CHANNEL_ID", int(os.getenv("DISASTER_CHANNEL_ID", "0") or 0))
        gen_channel_id = await self._get_int("GENERAL_CHANNEL_ID", int(os.getenv("GENERAL_CHANNEL_ID", "0") or 0))
        poll_min = await self._get_int("DISASTER_POLL_MINUTES", int(os.getenv("DISASTER_POLL_MINUTES", "5")))
        digest_time = await self._get("DIGEST_TIME_UTC", os.getenv("DIGEST_TIME_UTC", "09:00"))
        min_mag = await self._get("USGS_MIN_MAG", os.getenv("USGS_MIN_MAG", "5.0"))
        ping_mag = await self._get("USGS_PING_MAG", os.getenv("USGS_PING_MAG", "6.8"))

        # toggles
        flags = []
        for key, label in [
            ("ENABLE_USGS", "USGS"),
            ("ENABLE_RELIEFWEB", "ReliefWeb Reports"),
            ("ENABLE_RW_DISASTERS", "ReliefWeb Disasters"),
            ("ENABLE_EONET", "EONET"),
            ("ENABLE_GDACS_JSON", "GDACS JSON"),
            ("ENABLE_GDACS", "GDACS RSS"),
            ("ENABLE_WHO", "WHO"),
            ("ENABLE_COPERNICUS", "Copernicus"),
            ("ENABLE_FIRMS", "FIRMS"),
        ]:
            flags.append(f"{label}:{await self._get(key, 'true')}")

        e = discord.Embed(title="🛰️ Disaster Watcher — Status", color=discord.Color.greyple())
        e.add_field(name="Realtime Channel", value=str(rt_channel_id), inline=True)
        e.add_field(name="Digest Channel", value=str(gen_channel_id), inline=True)
        e.add_field(name="Poll Interval", value=f"{poll_min} min", inline=True)
        e.add_field(name="Digest Time (UTC)", value=digest_time, inline=True)
        e.add_field(name="USGS Min/Ping", value=f"{min_mag}/{ping_mag}", inline=True)
        e.add_field(name="Sources", value=" • ".join(flags), inline=False)
        e.add_field(name="Last Poll UTC", value=(self._last_poll_dt.isoformat() if self._last_poll_dt else "—"), inline=True)
        e.add_field(name="Last Poll Fetched", value=str(self._last_poll_fetched), inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # -------------------- loops --------------------

    @tasks.loop(minutes=5, reconnect=True)
    async def poll_disasters(self):
        try:
            # refresh dynamic intervals / channels every cycle
            interval = await self._get_int("DISASTER_POLL_MINUTES", int(os.getenv("DISASTER_POLL_MINUTES", "5")))
            if self.poll_disasters.seconds // 60 != interval:
                self.poll_disasters.change_interval(minutes=interval)

            rt_channel_id = await self._get_int("DISASTER_CHANNEL_ID", int(os.getenv("DISASTER_CHANNEL_ID", "0") or 0))
            alert_role = await self._get("ALERT_ROLE_NAME", os.getenv("ALERT_ROLE_NAME", "Disaster Alerts"))
            min_mag = await self._get_float("USGS_MIN_MAG", float(os.getenv("USGS_MIN_MAG", "5.0")))
            ping_mag = await self._get_float("USGS_PING_MAG", float(os.getenv("USGS_PING_MAG", "6.8")))
            rw_limit = await self._get_int("RELIEFWEB_LIMIT", int(os.getenv("RELIEFWEB_LIMIT", "5") or 5))
            rw_app = await self._get("RELIEFWEB_APPNAME", os.getenv("RELIEFWEB_APPNAME", "pal-discord-bot"))
            firms_url = await self._get("FIRMS_URL", os.getenv("FIRMS_URL", ""))

            use = {
                "usgs": await self._get_bool("ENABLE_USGS", True),
                "rw_reports": await self._get_bool("ENABLE_RELIEFWEB", True),
                "rw_dis": await self._get_bool("ENABLE_RW_DISASTERS", False),
                "eonet": await self._get_bool("ENABLE_EONET", True),
                "gdacs_json": await self._get_bool("ENABLE_GDACS_JSON", True),
                "gdacs": await self._get_bool("ENABLE_GDACS", True),
                "who": await self._get_bool("ENABLE_WHO", True),
                "copernicus": await self._get_bool("ENABLE_COPERNICUS", True),
                "firms": await self._get_bool("ENABLE_FIRMS", False),
                # Add these new ones:
                "nws": await self._get_bool("ENABLE_NWS", False),
                "nhc": await self._get_bool("ENABLE_NHC", True),
                "ptwc": await self._get_bool("ENABLE_PTWC", True),
                "gvp": await self._get_bool("ENABLE_GVP", True),
                "floodlist": await self._get_bool("ENABLE_FLOODLIST", True),
            }

            logging.info("Disasters: polling sources...")
            calls = []
            if use["usgs"]:         calls.append(self.fetch_usgs(min_mag))
            if use["rw_reports"]:   calls.append(self.fetch_reliefweb_reports(rw_limit, rw_app))
            if use["rw_dis"]:       calls.append(self.fetch_reliefweb_disasters(rw_limit, rw_app))
            if use["eonet"]:        calls.append(self.fetch_eonet())
            if use["gdacs_json"]:   calls.append(self.fetch_gdacs_json())
            if use["gdacs"]:        calls.append(self.fetch_gdacs_rss())
            if use["who"]:          calls.append(self.fetch_who_don())
            if use["copernicus"]:   calls.append(self.fetch_copernicus())
            if use["firms"] and firms_url: calls.append(self.fetch_firms(firms_url))
            # Add these new fetchers:
            if use["nws"]:          calls.append(self.fetch_nws())
            if use["nhc"]:          calls.append(self.fetch_nhc())
            if use["ptwc"]:         calls.append(self.fetch_ptwc())
            if use["gvp"]:          calls.append(self.fetch_gvp())
            if use["floodlist"]:    calls.append(self.fetch_floodlist())

            results = await asyncio.gather(*calls, return_exceptions=True)

            fetched = 0
            for res in results:
                if isinstance(res, Exception):
                    logging.exception("Disasters: fetch error", exc_info=res)
                    continue
                await self._handle_items(res, alert_role_name=alert_role, ping_mag=ping_mag, rt_channel_id=rt_channel_id)
                fetched += len(res)

            self._last_poll_dt = datetime.now(timezone.utc)
            self._last_poll_fetched = fetched
            logging.info("Disasters: poll complete — %s items (pre de-dupe).", fetched)
        except Exception as e:
            logging.exception("Disasters: poll loop error", exc_info=e)

    @poll_disasters.before_loop
    async def _wait_ready_poll(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def check_digest(self):
        try:
            general_channel_id = await self._get_int("GENERAL_CHANNEL_ID", int(os.getenv("GENERAL_CHANNEL_ID", "0") or 0))
            if not general_channel_id:
                return
            tstr = await self._get("DIGEST_TIME_UTC", os.getenv("DIGEST_TIME_UTC", "09:00"))
            try:
                hh, mm = map(int, tstr.split(":"))
                target = dtime(hour=hh, minute=mm, tzinfo=timezone.utc)
            except Exception:
                target = dtime(hour=9, minute=0, tzinfo=timezone.utc)

            now_dt = datetime.now(timezone.utc)
            today_key = now_dt.strftime("%Y-%m-%d")
            if self._last_digest_date == today_key:
                return

            target_dt = datetime.combine(now_dt.date(), target)
            if abs((now_dt - target_dt).total_seconds()) > 90:
                return

            if not self._digest_items:
                logging.info("Disasters: digest window hit, but no items collected.")
                self._last_digest_date = today_key
                return

            ch = self._channel(general_channel_id)
            if not ch:
                logging.warning("Disasters: GENERAL_CHANNEL_ID not found.")
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
    async def _wait_ready_digest(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Disasters(bot))
