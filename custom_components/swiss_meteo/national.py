"""What the map of Switzerland shows: the daily forecast of a fixed list of
places, the official warnings of the whole country and the newest radar
frames.

Nothing here runs on a schedule. Each layer is read when a card asks for it
and kept for as long as it stays current, once per Home Assistant however
many cards and entries there are:

* Forecast: the three daily files are small enough to be read whole (about
  0.2 MB each compressed, all 5800 points of the country), at most every
  three hours.
* Warnings: the MeteoAlarm feed the entries read anyway; no further request.
* Radar: the composite files of the last hour (30 to 160 KB each).
"""
from __future__ import annotations

import asyncio
import base64
import csv
import io
import logging
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import DOMAIN, USER_AGENT
from .meteoalarm import FeedEntry
from .ogd import OgdError, OgdUnavailable, async_find_latest_run, forecast_file_url
from .radar import COLS, LEVELS, PALETTE, RadarError, _level, _png, decode_field, frame_url, lv95, slot

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=60, sock_connect=15)
_FORECAST_MAX_AGE = timedelta(hours=3)
_FORECAST_KEEP = timedelta(hours=12)  # an older forecast is not shown any more
_RETRY_AFTER = timedelta(minutes=10)  # after a failed read
_PARAMS = {"jp2000d0": "symbol", "tre200px": "high", "tre200pn": "low"}

Account = Callable[[int, int], None]


@dataclass(frozen=True)
class Place:
    """A postal-code point of the local forecast shown on the map. Tier 1
    places are always shown, the others once the map is zoomed in."""

    point_id: int
    name: str
    lat: float
    lon: float
    tier: int


PLACES = (
    # point ids and coordinates from the forecast point list of 2026-11-24
    Place(800100, "Zürich", 47.372289, 8.542189, 1),
    Place(301100, "Bern", 46.947708, 7.445861, 1),
    Place(400100, "Basel", 47.55675, 7.588633, 1),
    Place(120400, "Genève", 46.202164, 6.146033, 1),
    Place(100300, "Lausanne", 46.520433, 6.631964, 1),
    Place(600300, "Luzern", 47.047869, 8.300947, 1),
    Place(900000, "St. Gallen", 47.423922, 9.374475, 1),
    Place(700000, "Chur", 46.855881, 9.526189, 1),
    Place(690000, "Lugano", 46.008308, 8.953075, 1),
    Place(195000, "Sion", 46.230603, 7.358856, 1),
    Place(750000, "St. Moritz", 46.491592, 9.835431, 1),
    Place(200000, "Neuchâtel", 46.994889, 6.928972, 2),
    Place(820000, "Schaffhausen", 47.704831, 8.635986, 2),
    Place(390000, "Brig", 46.317075, 7.990064, 2),
    Place(380000, "Interlaken", 46.684258, 7.859283, 2),
    Place(170000, "Fribourg", 46.804358, 7.155722, 2),
    Place(755000, "Scuol", 46.796786, 10.299706, 2),
    Place(646000, "Altdorf", 46.878097, 8.639806, 2),
    Place(875000, "Glarus", 47.042469, 9.064219, 2),
)

# The part of the radar composite the map shows, in pixels of the composite
# (1 km): LV95 2 475 000 to 2 845 000 east, 1 305 000 to 1 065 000 north.
_R_EAST, _R_NORTH = 2475, 1305
_R_W, _R_H = 370, 240
_R_COL, _R_ROW = _R_EAST - 2255, 1480 - _R_NORTH
_RADAR_FRAMES = 13  # an hour


def km(lat: float, lon: float) -> tuple[float, float]:
    """LV95 kilometres, the coordinates of the map."""
    east, north = lv95(lat, lon)
    return round(east / 1000, 2), round(north / 1000, 2)


def parse_daily(bodies: dict[str, bytes]) -> list[dict[str, Any]]:
    """The places' days out of the three whole daily files."""
    wanted = {str(p.point_id): p for p in PLACES}
    found: dict[str, dict[str, dict[str, float]]] = {}
    for param, body in bodies.items():
        key = _PARAMS[param]
        for row in csv.reader(io.StringIO(body.decode("latin-1")), delimiter=";"):
            if len(row) < 4 or row[0] not in wanted or row[1] != "2":
                continue
            try:
                value = float(row[3])
            except ValueError:
                continue
            found.setdefault(row[0], {}).setdefault(row[2][:8], {})[key] = value
    out: list[dict[str, Any]] = []
    for pid, place in wanted.items():
        days = [{"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", **values} for d, values in sorted(found.get(pid, {}).items())]
        if days:
            e, n = km(place.lat, place.lon)
            out.append({"name": place.name, "e": e, "n": n, "tier": place.tier, "days": days})
    return out


def _thin(ring: list[tuple[float, float]]) -> list[list[float]]:
    """The ring in LV95 kilometres on a 200 m grid, repeated points dropped."""
    out: list[list[float]] = []
    for lat, lon in ring:
        east, north = lv95(lat, lon)
        point = [round(east / 200) / 5, round(north / 200) / 5]
        if not out or out[-1] != point:
            out.append(point)
    return out


def warning_areas(entries: list[FeedEntry], now: datetime) -> list[dict[str, Any]]:
    """The warnings in force or announced, weakest first (drawn in this order)."""
    order = {"yellow": 0, "orange": 1, "red": 2}
    out: list[dict[str, Any]] = []
    for entry in entries:
        if not entry.actual or entry.level not in order or not entry.rings:
            continue
        if entry.expires is not None and entry.expires <= now:
            continue
        out.append(
            {
                "level": entry.level,
                "kind": entry.kind,
                "area": entry.area,
                "onset": entry.onset.isoformat() if entry.onset else None,
                "expires": entry.expires.isoformat() if entry.expires else None,
                "rings": [ring for ring in (_thin(r) for r in entry.rings) if len(ring) >= 4],
            }
        )
    return sorted(out, key=lambda item: order[item["level"]])


def render_national(raw: bytes) -> str:
    """The Swiss part of a composite file as a base64 PNG."""
    field = decode_field(raw)
    pixels = bytearray(_R_W * _R_H)
    for r in range(_R_H):
        base = (_R_ROW + r) * COLS + _R_COL
        for c, value in enumerate(field[base : base + _R_W]):
            if value >= LEVELS[0]:  # False for NaN
                pixels[r * _R_W + c] = _level(value)
    return base64.b64encode(_png(_R_W, _R_H, bytes(pixels))).decode()


class NationalData:
    """The map's layers, kept between requests."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._lock = asyncio.Lock()
        self._radar_lock = asyncio.Lock()
        self._forecast: list[dict[str, Any]] = []
        self._run: datetime | None = None
        self._read_at: datetime | None = None
        self._failed_at: datetime | None = None
        self._frames: dict[datetime, str] = {}
        self._radar_tried: datetime | None = None

    async def _get(self, session: aiohttp.ClientSession, url: str, account: Account | None) -> bytes:
        try:
            async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise OgdUnavailable(f"HTTP {resp.status} for {url.rsplit('/', 1)[-1]}")
                body = await resp.read()
                stated = resp.headers.get("Content-Length", "")
                coded = resp.headers.get("Content-Encoding")
        except (TimeoutError, aiohttp.ClientError) as err:
            raise OgdUnavailable(f"{type(err).__name__} for {url.rsplit('/', 1)[-1]}") from err
        if account is not None:
            # Compressed answers come in chunks without a length: what they
            # weighed is measured by compressing the body again (0.5 % off).
            if stated.isdigit():
                size = int(stated)
            elif coded:
                size = len(await self._hass.async_add_executor_job(zlib.compress, body))
            else:
                size = len(body)
            account(1, size)
        return body

    async def async_forecast(self, account: Account | None = None) -> dict[str, Any]:
        async with self._lock:
            now = dt_util.utcnow()
            today = dt_util.now().date()
            stale = (
                self._read_at is None
                or now - self._read_at >= _FORECAST_MAX_AGE
                or dt_util.as_local(self._read_at).date() != today
            )
            backoff = self._failed_at is not None and now - self._failed_at < _RETRY_AFTER
            if stale and not backoff:
                try:
                    session = async_get_clientsession(self._hass)
                    run = await async_find_latest_run(session, now)
                    if run is None:
                        raise OgdUnavailable("no forecast run for the last hours")
                    bodies = {p: await self._get(session, forecast_file_url(run, p), account) for p in _PARAMS}
                    places = await self._hass.async_add_executor_job(parse_daily, bodies)
                    if not places:
                        raise OgdError("the daily files hold none of the map's places")
                    self._forecast, self._run, self._read_at, self._failed_at = places, run, now, None
                except OgdError as err:
                    self._failed_at = now
                    _LOGGER.debug("Map forecast not read: %s", err)
            if self._read_at is None or now - self._read_at > _FORECAST_KEEP:
                return {"run": None, "places": []}
            iso = today.isoformat()
            places = [{**p, "days": [d for d in p["days"] if d["date"] >= iso]} for p in self._forecast]
            return {"run": self._run.isoformat() if self._run else None, "places": places}

    async def async_radar(self, account: Account | None = None) -> dict[str, Any]:
        async with self._radar_lock:
            now = dt_util.utcnow()
            newest = slot(now)
            if self._radar_tried is None or now - self._radar_tried >= timedelta(minutes=1):
                self._radar_tried = now
                session = async_get_clientsession(self._hass)
                for n in range(_RADAR_FRAMES):
                    ts = newest - timedelta(minutes=5 * n)
                    if ts in self._frames:
                        continue
                    try:
                        raw = await self._get(session, frame_url(ts), account)
                        self._frames[ts] = await self._hass.async_add_executor_job(render_national, raw)
                    except (OgdUnavailable, RadarError) as err:
                        _LOGGER.debug("Map radar frame %s not read: %s", ts, err)
                        if n > 1:  # the newest two may not be published yet
                            break
            oldest = newest - timedelta(minutes=5 * _RADAR_FRAMES)
            self._frames = {ts: png for ts, png in self._frames.items() if ts > oldest}
            return {
                "origin": {"e": _R_EAST, "n": _R_NORTH},
                "size": {"w": _R_W, "h": _R_H},
                "levels": list(LEVELS),
                "palette": [list(c) for c in PALETTE],
                "frames": [{"ts": ts.astimezone(UTC).isoformat(), "png": png} for ts, png in sorted(self._frames.items())],
            }


_DATA_KEY = f"{DOMAIN}_national"


def national(hass: HomeAssistant) -> NationalData:
    """The one store of the map's layers."""
    if _DATA_KEY not in hass.data:
        hass.data[_DATA_KEY] = NationalData(hass)
    return hass.data[_DATA_KEY]
