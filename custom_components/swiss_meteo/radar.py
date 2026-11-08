"""Radar: the MeteoSwiss precipitation composite (PRECIP, product RZC),
one 1 km field of rain rates every five minutes, 29 KB per file, read
around the forecast point.

From the newest frames the integration derives what the forecast cannot
say: is it raining here right now, how far away is the nearest rain, and
how the rain field moves — so an estimate of when rain reaches the point
can be given for the next hour or two. The official nowcast (INCA) is not
open data; this is the integration's own extrapolation and is labelled
as an estimate.

The files are HDF5 (ODIM_H5) with one gzip-compressed chunk holding the
640×710 field as big-endian doubles. That chunk is found by scanning for
the zlib stream and inflating it — no HDF5 library is needed, the result
is identical to a library read (verified against h5py)."""
from __future__ import annotations

import logging
import math
import struct
import zlib
from array import array
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_POINT_LAT, CONF_POINT_LON, DATA_BASE, DOMAIN, USER_AGENT

_LOGGER = logging.getLogger(__name__)

COLLECTION_RADAR = "ch.meteoschweiz.ogd-radar-precip"
RADAR_BASE = f"{DATA_BASE}/{COLLECTION_RADAR}"
UPDATE_INTERVAL = timedelta(minutes=5)
_TIMEOUT = aiohttp.ClientTimeout(total=40, sock_connect=10)
_MAX_AGE = timedelta(minutes=25)  # older frames are no "now" any more

# The composite grid (LV95, 1 km pixels): columns east from 2 255 000 m,
# rows south from 1 480 000 m. Verified against the corner coordinates
# and the projection definition stored in the files.
COLS, ROWS = 710, 640
X0, Y0 = 2_255_000, 1_480_000
_PIXEL_M = 1000
_FIELD_BYTES = COLS * ROWS * 8

RAIN_MIN = 0.1  # mm/h: "it rains" at the point
RAIN_CELL = 0.5  # mm/h: a rain cell worth tracking
SEARCH_KM = 60  # how far the nearest rain is looked for
WINDOW_KM = 80  # motion is estimated from the rain within this window
MAX_SHIFT = 12  # px per 5 min (144 km/h), search limit for the motion
ETA_MAX_MIN = 120


class RadarError(Exception):
    """A frame could not be read or made no sense."""


def lv95(lat: float, lon: float) -> tuple[float, float]:
    """WGS84 -> Swiss LV95 (swisstopo approximation, metres)."""
    phi = (lat * 3600 - 169028.66) / 10000
    lam = (lon * 3600 - 26782.5) / 10000
    east = 2600072.37 + 211455.93 * lam - 10938.51 * lam * phi - 0.36 * lam * phi**2 - 44.54 * lam**3
    north = 1200147.07 + 308807.95 * phi + 3745.25 * lam**2 + 76.63 * phi**2 - 194.56 * lam**2 * phi + 119.79 * phi**3
    return east, north


def pixel_of(lat: float, lon: float) -> tuple[int, int]:
    """(row, col) of a WGS84 point in the composite."""
    east, north = lv95(lat, lon)
    return int((Y0 - north) // _PIXEL_M), int((east - X0) // _PIXEL_M)


def frame_url(ts: datetime) -> str:
    """URL of the PRECIP frame ending at `ts` (UTC, multiple of 5 min)."""
    ts = ts.astimezone(timezone.utc)
    return f"{RADAR_BASE}/{ts:%Y%m%d}-ch/rzc{ts:%y}{ts.timetuple().tm_yday:03d}{ts:%H%M}vl.001.h5"


def slot(now: datetime) -> datetime:
    """The newest 5-minute slot that is normally published (frames appear
    about a minute after the slot ends)."""
    now = now.astimezone(timezone.utc) - timedelta(minutes=1)
    return now.replace(second=0, microsecond=0, minute=now.minute - now.minute % 5)


def decode_field(raw: bytes) -> array:
    """The 640×710 rain-rate field (mm/h, NaN = outside coverage) from an
    RZC file: the single gzip chunk, found by scanning for its zlib header."""
    i = 0
    while True:
        i = raw.find(b"\x78", i)
        if i < 0 or i + 1 >= len(raw):
            raise RadarError("no zlib stream in the radar file")
        if raw[i + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            try:
                out = zlib.decompressobj().decompress(raw[i:])
            except zlib.error:
                out = b""
            if len(out) == _FIELD_BYTES:
                field = array("d", struct.unpack(f">{COLS * ROWS}d", out))
                return field
        i += 1


@dataclass
class Frame:
    ts: datetime  # end of the 5-minute interval, UTC
    field: array


@dataclass
class RadarData:
    frame_ts: datetime
    rate: float  # mm/h at the point (3×3 maximum)
    rate_point: float  # mm/h at the exact pixel
    raining: bool
    nearest_km: float | None  # distance to the nearest rain cell, None if none within SEARCH_KM
    nearest_bearing: float | None  # where that rain is, degrees from north
    speed_kmh: float | None  # motion of the rain field near the point
    direction: float | None  # direction the rain moves towards, degrees
    eta_min: int | None  # minutes until rain reaches the point (0 if raining), None if not expected within ETA_MAX_MIN
    rain_pixels_window: int  # rain cells within the window
    fetched: datetime

    @property
    def approaching(self) -> bool:
        return self.raining or (self.eta_min is not None and self.eta_min <= 30)


def _value(field: array, r: int, c: int) -> float:
    if 0 <= r < ROWS and 0 <= c < COLS:
        v = field[r * COLS + c]
        return 0.0 if v != v else v  # NaN -> 0
    return 0.0


def analyse(frames: list[Frame], r0: int, c0: int, now: datetime) -> RadarData:
    """What the newest frame (and the one before) say about the point."""
    cur = frames[-1]
    f = cur.field
    rate_point = _value(f, r0, c0)
    rate = max(_value(f, r0 + dr, c0 + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1))
    raining = rate >= RAIN_MIN

    # rain cells within the window, as (dr, dc, rate)
    cells: list[tuple[int, int, float]] = []
    for dr in range(-WINDOW_KM, WINDOW_KM + 1):
        r = r0 + dr
        if not 0 <= r < ROWS:
            continue
        base = r * COLS
        for dc in range(-WINDOW_KM, WINDOW_KM + 1):
            c = c0 + dc
            if 0 <= c < COLS:
                v = f[base + c]
                if v == v and v >= RAIN_CELL:
                    cells.append((dr, dc, v))

    nearest_km = nearest_bearing = None
    for dr, dc, _v in cells:
        d = math.hypot(dr, dc)
        if d <= SEARCH_KM and (nearest_km is None or d < nearest_km):
            nearest_km = d
            nearest_bearing = (math.degrees(math.atan2(dc, -dr)) + 360) % 360  # dc east, -dr north

    speed = direction = None
    eta = 0 if raining else None
    if len(frames) >= 2 and cells:
        shift = _motion(frames[-2].field, f, r0, c0)
        if shift is not None:
            dy, dx = shift  # px per 5 min the field moved (new = old shifted by dy, dx)
            dt_min = max(1.0, (cur.ts - frames[-2].ts).total_seconds() / 60)
            vy, vx = dy / dt_min, dx / dt_min  # px per minute
            v = math.hypot(vy, vx)
            speed = round(v * 60, 1)
            direction = (math.degrees(math.atan2(vx, -vy)) + 360) % 360 if v > 0.02 else None
            if not raining and v > 0.02:
                best = None
                for dr, dc, _v in cells:
                    # time until the cell's centre passes within 1.5 km of the point
                    # solve |(dr, dc) + t (vy, vx)| minimal
                    t = -(dr * vy + dc * vx) / (v * v)
                    if t <= 0:
                        continue
                    miss = math.hypot(dr + t * vy, dc + t * vx)
                    if miss <= 1.5 and (best is None or t < best):
                        best = t
                if best is not None and best <= ETA_MAX_MIN:
                    eta = int(round(best))
    return RadarData(
        frame_ts=cur.ts,
        rate=round(rate, 2),
        rate_point=round(rate_point, 2),
        raining=raining,
        nearest_km=round(nearest_km, 1) if nearest_km is not None else None,
        nearest_bearing=round(nearest_bearing) if nearest_bearing is not None else None,
        speed_kmh=speed,
        direction=round(direction) if direction is not None else None,
        eta_min=eta,
        rain_pixels_window=len(cells),
        fetched=now,
    )


def _motion(prev: array, cur: array, r0: int, c0: int) -> tuple[int, int] | None:
    """The shift (dy, dx) in pixels that best maps the previous frame's rain
    near the point onto the current one; None without enough rain."""
    pts: list[tuple[int, int, float]] = []
    step = 1
    for r in range(max(0, r0 - WINDOW_KM), min(ROWS, r0 + WINDOW_KM + 1), step):
        base = r * COLS
        for c in range(max(0, c0 - WINDOW_KM), min(COLS, c0 + WINDOW_KM + 1), step):
            v = prev[base + c]
            if v == v and v >= 0.3:
                pts.append((r, c, v))
    if len(pts) < 20:
        return None
    if len(pts) > 2500:  # thin out evenly, keeps the work bounded
        k = len(pts) / 2500
        pts = [pts[int(i * k)] for i in range(2500)]
    best: tuple[float, int, int] | None = None
    for dy in range(-MAX_SHIFT, MAX_SHIFT + 1):
        for dx in range(-MAX_SHIFT, MAX_SHIFT + 1):
            s = 0.0
            n = 0
            for r, c, v in pts:
                rr, cc = r + dy, c + dx
                if 0 <= rr < ROWS and 0 <= cc < COLS:
                    w = cur[rr * COLS + cc]
                    d = v - (0.0 if w != w else w)
                    s += d * d
                    n += 1
            if n >= 20:
                score = s / n
                if best is None or score < best[0]:
                    best = (score, dy, dx)
    if best is None:
        return None
    return best[1], best[2]


class RadarCoordinator(DataUpdateCoordinator[RadarData]):
    """The newest radar frames around the entry's point."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, account=None) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} radar", update_interval=UPDATE_INTERVAL, config_entry=entry)
        self.entry = entry
        self.row, self.col = pixel_of(float(entry.data[CONF_POINT_LAT]), float(entry.data[CONF_POINT_LON]))
        self._frames: deque[Frame] = deque(maxlen=3)
        self._account = account
        self._warned = False
        if not (0 <= self.row < ROWS and 0 <= self.col < COLS):
            raise ValueError("point outside the radar composite")

    async def _fetch(self, session: aiohttp.ClientSession, ts: datetime) -> bytes | None:
        async with session.get(frame_url(ts), headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT) as resp:
            if resp.status == 404:
                return None
            if resp.status != 200:
                raise RadarError(f"radar answered {resp.status}")
            return await resp.read()

    async def _async_update_data(self) -> RadarData:
        now = dt_util.utcnow()
        session = async_get_clientsession(self.hass)
        want = slot(now)
        have = {fr.ts for fr in self._frames}
        requests = 0
        nbytes = 0
        try:
            # the newest slot, else the one before (publication lag); also fill the previous slot for the motion
            for ts in (want, want - timedelta(minutes=5), want - timedelta(minutes=10)):
                if ts in have:
                    continue
                if self._frames and ts < self._frames[-1].ts:
                    continue
                raw = await self._fetch(session, ts)
                requests += 1
                if raw is None:
                    continue
                nbytes += len(raw)
                field = await self.hass.async_add_executor_job(decode_field, raw)
                self._frames.append(Frame(ts=ts, field=field))
                self._frames = deque(sorted(self._frames, key=lambda fr: fr.ts), maxlen=3)
                break
            else:
                if not self._frames:
                    raise RadarError("no radar frame for the last 15 minutes")
            # make sure the frame before the newest is there for the motion estimate
            newest = self._frames[-1].ts
            prev_ts = newest - timedelta(minutes=5)
            if len(self._frames) < 2 or self._frames[-2].ts != prev_ts:
                raw = await self._fetch(session, prev_ts)
                requests += 1
                if raw is not None:
                    nbytes += len(raw)
                    field = await self.hass.async_add_executor_job(decode_field, raw)
                    self._frames = deque(sorted([*self._frames, Frame(ts=prev_ts, field=field)], key=lambda fr: fr.ts), maxlen=3)
        except (aiohttp.ClientError, TimeoutError, RadarError) as err:
            if self._frames and now - self._frames[-1].ts <= _MAX_AGE:
                if not self._warned:
                    self._warned = True
                    _LOGGER.warning("Radar frame not read, keeping the last one: %s", err)
            else:
                raise UpdateFailed(str(err)) from err
        finally:
            if self._account is not None and requests:
                self._account(requests, nbytes)
        self._warned = False
        if now - self._frames[-1].ts > _MAX_AGE:
            raise UpdateFailed(f"newest radar frame is from {self._frames[-1].ts:%H:%M} UTC")
        return await self.hass.async_add_executor_job(analyse, list(self._frames), self.row, self.col, now)

    @property
    def fresh(self) -> bool:
        return self.data is not None and dt_util.utcnow() - self.data.frame_ts <= _MAX_AGE
