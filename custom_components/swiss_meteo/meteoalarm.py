"""Official severe-weather warnings.

MeteoSwiss publishes its warnings through MeteoAlarm, the EUMETNET
warning service, in the Common Alerting Protocol. Switzerland's alerts
carry the warned area as polygons, so the alerts that matter for an entry
are found by testing the forecast point against them: no region list,
no API key, one small public JSON feed read every ten minutes.

Levels are MeteoAlarm's three colours: yellow (moderate), orange
(severe), red (extreme)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_POINT_LAT, CONF_POINT_LON, DOMAIN, USER_AGENT

_LOGGER = logging.getLogger(__name__)

WARNINGS_URL = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-switzerland"
UPDATE_INTERVAL = timedelta(minutes=10)
_MAX_AGE = timedelta(hours=2)  # a failed read keeps the last list this long
_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=10)

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


# --- coordinator ---------------------------------------------------------------


class WarningsCoordinator(DataUpdateCoordinator[WarningsData]):
    """The warnings in force or announced for the entry's point."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} warnings", update_interval=UPDATE_INTERVAL, config_entry=entry)
        self.entry = entry
        self.lat = float(entry.data[CONF_POINT_LAT])
        self.lon = float(entry.data[CONF_POINT_LON])
        self._warned = False

    async def _async_update_data(self) -> WarningsData:
        now = dt_util.utcnow()
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(WARNINGS_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise WarningsError(f"MeteoAlarm answered {resp.status}")
                payload = await resp.json(content_type=None)
                if not isinstance(payload, dict):
                    raise WarningsError("MeteoAlarm feed is not a JSON object")
        except (aiohttp.ClientError, TimeoutError, ValueError, WarningsError) as err:
            if self.data is not None and now - self.data.fetched <= _MAX_AGE:
                if not self._warned:
                    self._warned = True
                    _LOGGER.warning("Warnings feed not read, keeping the last list: %s", err)
                return self.data
            raise UpdateFailed(str(err)) from err
        self._warned = False
        return parse_warnings(payload, self.lat, self.lon, self.hass.config.language, now)

    @property
    def fresh(self) -> bool:
        return self.data is not None and dt_util.utcnow() - self.data.fetched <= _MAX_AGE
