"""Official severe-weather warnings.

MeteoSwiss publishes its warnings through MeteoAlarm, the EUMETNET
warning service, in the Common Alerting Protocol. Switzerland's alerts
carry the warned area as polygons, so the alerts that matter for an entry
are found by testing the forecast point against them: no region list,
no API key. The list of alerts in force is read from MeteoAlarm's Atom
feed; the few alerts that cover the point are then read in full.

Levels are MeteoAlarm's three colours: yellow (moderate), orange
(severe), red (extreme)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from xml.etree import ElementTree

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .issues import IssueReporter
from .traffic import Account, transferred
from .const import CONF_POINT_LAT, CONF_POINT_LON, DOMAIN, USER_AGENT

_LOGGER = logging.getLogger(__name__)

# The alerts in force for Switzerland, one entry each (see "the feed" below).
WARNINGS_URL = "https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-switzerland"
UPDATE_INTERVAL = timedelta(minutes=10)  # how often the feed's length is asked
FULL_MAX_AGE = timedelta(minutes=60)  # the feed is read again at the latest after this
_MAX_AGE = timedelta(hours=2)  # a failed read keeps the last list this long
_TIMEOUT = aiohttp.ClientTimeout(total=60, sock_connect=10)
# No Accept header: asked for XML types by name, the server answers with something else.
_HEADERS = {"User-Agent": USER_AGENT}

LEVELS = ("none", "yellow", "orange", "red")
LEVEL_BY_CODE = {2: "yellow", 3: "orange", 4: "red"}

# MeteoAlarm awareness types (CAP profile v2.0)
TYPES = {
    1: "wind",
    2: "snow_ice",
    3: "thunderstorm",
    4: "fog",
    5: "high_temperature",
    6: "low_temperature",
    7: "coastal_event",
    8: "forest_fire",
    9: "avalanches",
    10: "rain",
    12: "flooding",
    13: "rain_flood",
    14: "marine",
    15: "drought",
}


class WarningsError(Exception):
    """The feed could not be read or made no sense."""


@dataclass
class Warning:
    identifier: str
    level: str  # yellow / orange / red
    level_code: int
    type_key: str
    type_code: int | None
    event: str
    headline: str
    description: str
    instruction: str
    onset: datetime | None
    expires: datetime | None
    sent: datetime | None
    areas: list[str]
    sender: str
    web: str
    language: str
    upcoming: bool  # onset still ahead at parse time (see is_upcoming)

    def is_upcoming(self, now: datetime) -> bool:
        return bool(self.onset and self.onset > now)

    def as_dict(self, now: datetime | None = None, brief: bool = False) -> dict[str, Any]:
        upcoming = self.is_upcoming(now) if now else self.upcoming
        out = {
            "event": self.event,
            "level": self.level,
            "type": self.type_key,
            "headline": self.headline,
            "onset": self.onset.isoformat() if self.onset else None,
            "expires": self.expires.isoformat() if self.expires else None,
            "areas": self.areas[:10],
            "upcoming": upcoming,
            "web": self.web,
        }
        if not brief:
            out["description"] = self.description
            out["instruction"] = self.instruction
        return out


@dataclass
class WarningsData:
    fetched: datetime
    items: list[Warning] = field(default_factory=list)  # those covering the point, active first, highest first
    total: int = 0  # alerts in the feed (whole country)
    unlocated: int = 0  # alerts without a polygon (cannot be placed)

    @property
    def active(self) -> list[Warning]:
        now = dt_util.utcnow()
        return [w for w in self.items if not w.is_upcoming(now)]

    @property
    def upcoming(self) -> list[Warning]:
        now = dt_util.utcnow()
        return [w for w in self.items if w.is_upcoming(now)]

    def level(self) -> str:
        """The highest colour of the warnings in force now."""
        active = self.active
        return max((w.level for w in active), key=LEVELS.index) if active else "none"

    def as_list(self, brief: bool = False) -> list[dict[str, Any]]:
        """The matching warnings as attributes, in force first, at most ten."""
        now = dt_util.utcnow()
        items = sorted(self.items, key=lambda w: (w.is_upcoming(now), -LEVELS.index(w.level), w.onset or now))
        return [w.as_dict(now, brief) for w in items[:10]]


# --- parsing ------------------------------------------------------------------


def _parse_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def parse_polygon(text: str) -> list[tuple[float, float]]:
    """A CAP polygon ("lat,lon lat,lon …") as a list of (lat, lon)."""
    ring: list[tuple[float, float]] = []
    for pair in str(text).split():
        try:
            lat_s, lon_s = pair.split(",")
            ring.append((float(lat_s), float(lon_s)))
        except ValueError:
            continue
    return ring


def point_in_ring(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    """Ray casting: is the point inside the closed ring?"""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        yi, xi = ring[i]
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


def _param(info: dict, name: str) -> str | None:
    for p in info.get("parameter") or []:
        if isinstance(p, dict) and p.get("valueName") == name:
            return str(p.get("value"))
    return None


def _code(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.split(";")[0].strip())
    except ValueError:
        return None


def _pick_info(infos: list[dict], language: str) -> dict:
    """The info block in the instance language, else English, else the first."""
    lang = (language or "en")[:2].lower()
    for info in infos:
        if str(info.get("language", "")).lower().startswith(lang):
            return info
    for info in infos:
        if str(info.get("language", "")).lower().startswith("en"):
            return info
    return infos[0]


def _polygons(info: dict) -> list[list[tuple[float, float]]]:
    rings: list[list[tuple[float, float]]] = []
    for area in info.get("area") or []:
        if not isinstance(area, dict):
            continue
        poly = area.get("polygon")
        if poly is None:
            continue
        for text in poly if isinstance(poly, list) else [poly]:
            ring = parse_polygon(text)
            if len(ring) >= 3:
                rings.append(ring)
    return rings


def parse_warnings(payload: dict, lat: float, lon: float, language: str, now: datetime) -> WarningsData:
    """The alerts of the feed that cover the point and are not expired."""
    data = WarningsData(fetched=now)
    seen: set[str] = set()
    entries = [e for e in payload.get("warnings") or [] if isinstance(e, dict) and isinstance(e.get("alert"), dict)]
    # an Update or Cancel names the alerts it replaces in `references` ("sender,identifier,sent" items)
    replaced: set[str] = set()
    for entry in entries:
        for ref in str(entry["alert"].get("references") or "").split():
            parts = ref.split(",")
            if len(parts) >= 2:
                replaced.add(parts[1])
    for entry in entries:
        alert = entry["alert"]
        infos = [i for i in alert.get("info") or [] if isinstance(i, dict)]
        if not infos:
            continue
        data.total += 1
        if str(alert.get("msgType", "Alert")).lower() == "cancel" or str(alert.get("status", "Actual")).lower() != "actual":
            continue
        identifier = str(alert.get("identifier") or entry.get("uuid") or "")
        if identifier in seen or identifier in replaced:
            continue
        info = _pick_info(infos, language)
        expires = _parse_time(info.get("expires"))
        if expires is not None and expires <= now:
            continue
        # the area is the same in every language; take polygons from any info that has them
        rings = _polygons(info)
        if not rings:
            for other in infos:
                rings = _polygons(other)
                if rings:
                    break
        if not rings:
            data.unlocated += 1
            continue
        if not any(point_in_ring(lat, lon, ring) for ring in rings):
            continue
        seen.add(identifier)
        level_param = _param(info, "awareness_level")
        level_code = _code(level_param) if level_param is not None else 2  # absent: treat as the lowest published colour
        if level_code is None or level_code < 2:
            continue  # green (no particular awareness) or unparsable
        type_code = _code(_param(info, "awareness_type"))
        onset = _parse_time(info.get("onset")) or _parse_time(info.get("effective"))
        data.items.append(
            Warning(
                identifier=identifier,
                level=LEVEL_BY_CODE.get(level_code, "red"),
                level_code=level_code,
                type_key=TYPES.get(type_code or -1, "other"),
                type_code=type_code,
                event=str(info.get("event") or "").strip(),
                headline=str(info.get("headline") or "").strip(),
                description=str(info.get("description") or "").strip()[:600],
                instruction=str(info.get("instruction") or "").strip()[:400],
                onset=onset,
                expires=expires,
                sent=_parse_time(alert.get("sent")),
                areas=[str(a.get("areaDesc") or "").strip() for a in info.get("area") or [] if isinstance(a, dict) and a.get("areaDesc")],
                sender=str(info.get("senderName") or alert.get("sender") or "").strip(),
                web=str(info.get("web") or "").strip(),
                language=str(info.get("language") or ""),
                upcoming=bool(onset and onset > now),
            )
        )
    data.items.sort(key=lambda w: (w.upcoming, -LEVELS.index(w.level), w.onset or now))
    return data


# --- the feed ------------------------------------------------------------------
#
# MeteoAlarm serves the Swiss alerts twice. The JSON feed carries every alert
# in full, five languages each with its polygon: 21 MB on a day with many
# warnings, uncompressed, with no way to ask for less. The Atom feed lists the
# alerts in force with one polygon each and a link to the alert itself: 1.7 MB
# on the same day, and it selected the same alerts for twenty places across
# Switzerland (compared on 2026-11-22). So the Atom feed says which alerts
# cover the point, and only those few are then read in full (about 45 KB each),
# once, for the texts in the instance language and the awareness level.
#
# Neither feed answers a conditional or a range request. A HEAD states the
# length, which changes with nearly every change of the list, so the feed is
# read again when its length changed and in any case after FULL_MAX_AGE (an
# alert replaced by one of exactly the same length would otherwise be missed).


@dataclass
class FeedEntry:
    """One alert of the Atom feed: enough to tell whether it covers a point."""

    identifier: str
    cap_url: str
    expires: datetime | None
    actual: bool
    rings: list[list[tuple[float, float]]]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_feed(body: bytes) -> list[FeedEntry]:
    """The entries of the Atom feed. Raises WarningsError for anything that
    is not such a feed."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as err:
        raise WarningsError(f"MeteoAlarm feed is not XML ({err})") from err
    if _local(root.tag) != "feed":
        raise WarningsError("MeteoAlarm feed is not an Atom feed")
    entries: list[FeedEntry] = []
    for node in root:
        if _local(node.tag) != "entry":
            continue
        fields: dict[str, str] = {}
        rings: list[list[tuple[float, float]]] = []
        cap_url = ""
        for child in node:
            name = _local(child.tag)
            if name == "polygon":
                ring = parse_polygon(child.text or "")
                if len(ring) >= 3:
                    rings.append(ring)
            elif name == "link":
                if "cap" in (child.get("type") or ""):
                    cap_url = child.get("href") or ""
            else:
                fields[name] = (child.text or "").strip()
        identifier = fields.get("identifier") or fields.get("id") or ""
        if not identifier:
            continue
        entries.append(
            FeedEntry(
                identifier=identifier,
                cap_url=cap_url,
                expires=_parse_time(fields.get("expires")),
                actual=fields.get("status", "Actual").lower() == "actual" and fields.get("message_type", "Alert").lower() != "cancel",
                rings=rings,
            )
        )
    return entries


_INFO_FIELDS = ("language", "event", "headline", "description", "instruction", "senderName", "web", "onset", "effective", "expires")
_ALERT_FIELDS = ("identifier", "sender", "sent", "status", "msgType", "references")


def parse_cap(body: bytes) -> dict[str, Any]:
    """One CAP alert (XML) as the mapping `parse_warnings` reads."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as err:
        raise WarningsError(f"MeteoAlarm alert is not XML ({err})") from err
    if _local(root.tag) != "alert":
        raise WarningsError("MeteoAlarm alert is not a CAP alert")
    alert: dict[str, Any] = {"info": []}
    for node in root:
        name = _local(node.tag)
        if name in _ALERT_FIELDS:
            alert[name] = (node.text or "").strip()
        elif name == "info":
            info: dict[str, Any] = {"parameter": [], "area": []}
            for child in node:
                key = _local(child.tag)
                if key in _INFO_FIELDS:
                    info[key] = (child.text or "").strip()
                elif key == "parameter":
                    pair = {_local(part.tag): (part.text or "").strip() for part in child}
                    info["parameter"].append({"valueName": pair.get("valueName"), "value": pair.get("value")})
                elif key == "area":
                    area: dict[str, Any] = {"polygon": []}
                    for part in child:
                        if _local(part.tag) == "areaDesc":
                            area["areaDesc"] = (part.text or "").strip()
                        elif _local(part.tag) == "polygon":
                            area["polygon"].append(part.text or "")
                    info["area"].append(area)
            alert["info"].append(info)
    return alert


def covering(entries: list[FeedEntry], lat: float, lon: float, now: datetime) -> list[FeedEntry]:
    """The entries in force whose area contains the point."""
    return [
        entry
        for entry in entries
        if entry.actual
        and (entry.expires is None or entry.expires > now)
        and any(point_in_ring(lat, lon, ring) for ring in entry.rings)
    ]


# --- coordinator ---------------------------------------------------------------

# Refreshes in a row without the feed before a Repairs notice (an hour).
_ISSUE_AFTER = 6


class WarningsCoordinator(DataUpdateCoordinator[WarningsData]):
    """The warnings in force or announced for the entry's point."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, account: Account | None = None) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} warnings", update_interval=UPDATE_INTERVAL, config_entry=entry)
        self.entry = entry
        self.lat = float(entry.data[CONF_POINT_LAT])
        self.lon = float(entry.data[CONF_POINT_LON])
        self.issues = IssueReporter(hass, entry.entry_id)
        self._account = account  # the entry's traffic counter
        self._warned = False
        self._entries: list[FeedEntry] | None = None  # the feed as last read
        self._length: str | None = None  # its length then
        self._read_at: datetime | None = None
        self._alerts: dict[str, dict[str, Any]] = {}  # alerts read in full, by identifier

    def _count(self, nbytes: int) -> None:
        if self._account is not None:
            self._account(1, nbytes)

    async def _feed_length(self, session: aiohttp.ClientSession) -> str | None:
        """What the feed weighs now, without reading it."""
        async with session.head(WARNINGS_URL, headers=_HEADERS, timeout=_TIMEOUT) as resp:
            self._count(0)
            if resp.status != 200:
                raise WarningsError(f"MeteoAlarm answered {resp.status}")
            return resp.headers.get("Content-Length")

    async def _get(self, session: aiohttp.ClientSession, url: str) -> bytes:
        async with session.get(url, headers=_HEADERS, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                self._count(0)
                raise WarningsError(f"MeteoAlarm answered {resp.status}")
            body = await resp.read()
            self._count(transferred(resp.headers, body))
            return body

    async def _async_read(self, now: datetime) -> WarningsData:
        session = async_get_clientsession(self.hass)
        due = self._entries is None or self._read_at is None or now - self._read_at >= FULL_MAX_AGE
        length: str | None = None
        if not due:
            length = await self._feed_length(session)
            due = length is not None and length != self._length
        if due:
            body = await self._get(session, WARNINGS_URL)
            self._entries = await self.hass.async_add_executor_job(parse_feed, body)
            self._length = length if length is not None else str(len(body))
            self._read_at = now
        entries = self._entries or []
        here = covering(entries, self.lat, self.lon, now)
        for entry in here:
            if entry.identifier not in self._alerts:
                if not entry.cap_url:
                    raise WarningsError("MeteoAlarm feed names no alert document")
                self._alerts[entry.identifier] = parse_cap(await self._get(session, entry.cap_url))
        listed = {entry.identifier for entry in entries}
        self._alerts = {identifier: alert for identifier, alert in self._alerts.items() if identifier in listed}
        payload = {"warnings": [{"alert": self._alerts[entry.identifier]} for entry in here]}
        data = parse_warnings(payload, self.lat, self.lon, self.hass.config.language, now)
        data.total = len(entries)
        data.unlocated = sum(1 for entry in entries if not entry.rings)
        return data

    async def _async_update_data(self) -> WarningsData:
        now = dt_util.utcnow()
        try:
            data = await self._async_read(now)
        except (aiohttp.ClientError, TimeoutError, ValueError, WarningsError) as err:
            # An hour without the feed is worth a word under Repairs.
            self.issues.failure("warnings_unreachable", {"error": str(err) or type(err).__name__}, after=_ISSUE_AFTER)
            if self.data is not None and now - self.data.fetched <= _MAX_AGE:
                if not self._warned:
                    self._warned = True
                    _LOGGER.warning("Warnings feed not read, keeping the last list: %s", err)
                return self.data
            raise UpdateFailed(str(err), translation_domain=DOMAIN, translation_key="read_failed", translation_placeholders={"error": str(err)}) from err
        self._warned = False
        self.issues.clear("warnings_unreachable")
        return data

    @property
    def fresh(self) -> bool:
        return self.data is not None and dt_util.utcnow() - self.data.fetched <= _MAX_AGE
