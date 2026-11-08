"""Radar: the MeteoSwiss precipitation composite (PRECIP, product RZC),
one 1 km field of rain rates every five minutes, 29 KB per file, read
around the forecast point.

From the newest frames the integration derives what the forecast cannot
say: is it raining here right now, how far away is the nearest rain, and
how the rain field moves — so an estimate of when rain reaches the point
can be given for the next hour or two. The last two hours of frames are
kept (as 200 × 200 km crops around the point) for the radar card, which
plays them as a loop and continues it with frames extrapolated along the
measured motion. The official nowcast (INCA) is not open data; this is the
integration's own extrapolation and is labelled as an estimate.

The files are HDF5 (ODIM_H5) with one gzip-compressed chunk holding the
640×710 field as big-endian doubles. That chunk is found by scanning for
the zlib stream and inflating it — no HDF5 library is needed, the result
is identical to a library read (verified against h5py)."""
from __future__ import annotations

import asyncio
import base64
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

CROP_RADIUS = 100  # km kept around the point (crop is 201 × 201 px)
CROP = 2 * CROP_RADIUS + 1
HISTORY_MINUTES = 120  # frames kept for the loop
FORECAST_MINUTES = 180  # extrapolated frames offered to the card (the card picks how many it shows)
RAIN_MIN = 0.1  # mm/h: "it rains" at the point
RAIN_CELL = 0.5  # mm/h: a rain cell worth tracking
SEARCH_KM = 60  # how far the nearest rain is looked for
WINDOW_KM = 80  # motion is estimated from the rain within this window
MAX_SHIFT = 12  # px per 5 min (144 km/h), search limit for the motion
ETA_MAX_MIN = 120

# rain-rate classes (mm/h, lower bounds) and their colours for the PNGs
LEVELS = (0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0)
PALETTE = ((0, 0, 0), (150, 205, 255), (80, 150, 255), (40, 200, 90), (255, 230, 60), (255, 150, 30), (235, 40, 40), (200, 40, 220))


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
                return array("d", struct.unpack(f">{COLS * ROWS}d", out))
        i += 1


def crop_field(field: array, r0: int, c0: int) -> array:
    """The CROP × CROP window around (r0, c0) as 32-bit floats; outside the
    composite, and where the composite has no data, the value is 0."""
    out = array("f", bytes(4 * CROP * CROP))
    for i in range(CROP):
        r = r0 - CROP_RADIUS + i
        if not 0 <= r < ROWS:
            continue
        base = r * COLS
        row_out = i * CROP
        for j in range(CROP):
            c = c0 - CROP_RADIUS + j
            if 0 <= c < COLS:
                v = field[base + c]
                if v == v and v > 0:
                    out[row_out + j] = v
    return out


def decode_crop(raw: bytes, r0: int, c0: int) -> array:
    return crop_field(decode_field(raw), r0, c0)


@dataclass
class Frame:
    ts: datetime  # end of the 5-minute interval, UTC
    crop: array  # CROP × CROP rain rates around the point


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
    motion: tuple[float, float] | None  # (rows, cols) per minute of the field
    frames: int  # frames held for the loop
    fetched: datetime

    @property
    def approaching(self) -> bool:
        return self.raining or (self.eta_min is not None and self.eta_min <= 30)


def _at(crop: array, r: int, c: int) -> float:
    if 0 <= r < CROP and 0 <= c < CROP:
        return crop[r * CROP + c]
    return 0.0


def analyse(frames: list[Frame], now: datetime) -> RadarData:
    """What the newest frame (and the one before) say about the point at
    the crop's centre."""
    cur = frames[-1]
    f = cur.crop
    m = CROP_RADIUS
    rate_point = _at(f, m, m)
    rate = max(_at(f, m + dr, m + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1))
    raining = rate >= RAIN_MIN

    cells: list[tuple[int, int, float]] = []  # (dr, dc, rate) within the window
    for i in range(m - WINDOW_KM, m + WINDOW_KM + 1):
        base = i * CROP
        for j in range(m - WINDOW_KM, m + WINDOW_KM + 1):
            v = f[base + j]
            if v >= RAIN_CELL:
                cells.append((i - m, j - m, v))

    nearest_km = nearest_bearing = None
    for dr, dc, _v in cells:
        d = math.hypot(dr, dc)
        if d <= SEARCH_KM and (nearest_km is None or d < nearest_km):
            nearest_km = d
            nearest_bearing = (math.degrees(math.atan2(dc, -dr)) + 360) % 360

    speed = direction = None
    motion = None
    eta = 0 if raining else None
    prev = next((fr for fr in reversed(frames[:-1]) if (cur.ts - fr.ts) <= timedelta(minutes=10)), None)
    if prev is not None and cells:
        shift = _motion(prev.crop, f)
        if shift is not None:
            dy, dx = shift
            dt_min = max(1.0, (cur.ts - prev.ts).total_seconds() / 60)
            vy, vx = dy / dt_min, dx / dt_min  # px per minute
            motion = (vy, vx)
            v = math.hypot(vy, vx)
            speed = round(v * 60, 1)
            direction = (math.degrees(math.atan2(vx, -vy)) + 360) % 360 if v > 0.02 else None
            if not raining and v > 0.02:
                best = None
                for dr, dc, _v in cells:
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
        motion=motion,
        frames=len(frames),
        fetched=now,
    )


def _motion(prev: array, cur: array) -> tuple[int, int] | None:
    """The shift (dy, dx) in pixels that best maps the previous crop's rain
    near the centre onto the current one; None without enough rain."""
    m = CROP_RADIUS
    pts: list[tuple[int, int, float]] = []
    for r in range(m - WINDOW_KM, m + WINDOW_KM + 1):
        base = r * CROP
        for c in range(m - WINDOW_KM, m + WINDOW_KM + 1):
            v = prev[base + c]
            if v >= 0.3:
                pts.append((r, c, v))
    if len(pts) < 20:
        return None
    if len(pts) > 2500:
        k = len(pts) / 2500
        pts = [pts[int(i * k)] for i in range(2500)]
    best: tuple[float, int, int] | None = None
    for dy in range(-MAX_SHIFT, MAX_SHIFT + 1):
        for dx in range(-MAX_SHIFT, MAX_SHIFT + 1):
            s = 0.0
            n = 0
            for r, c, v in pts:
                rr, cc = r + dy, c + dx
                if 0 <= rr < CROP and 0 <= cc < CROP:
                    d = v - cur[rr * CROP + cc]
                    s += d * d
                    n += 1
            if n >= 20:
                score = s / n
                if best is None or score < best[0]:
                    best = (score, dy, dx)
    return (best[1], best[2]) if best else None


# --- PNG rendering ---------------------------------------------------------------


def _level(v: float) -> int:
    n = 0
    for bound in LEVELS:
        if v >= bound:
            n += 1
    return n


def _png(width: int, height: int, pixels: bytes) -> bytes:
    """An 8-bit indexed PNG with PALETTE (index 0 transparent)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + pixels[y * width:(y + 1) * width] for y in range(height))
    plte = b"".join(bytes(c) for c in PALETTE)
    trns = bytes([0] + [255] * (len(PALETTE) - 1))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
            + chunk(b"PLTE", plte) + chunk(b"tRNS", trns) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def render_png(crop: array, shift: tuple[int, int] = (0, 0)) -> bytes:
    """The crop as a PNG, optionally shifted by (rows, cols) pixels (the
    extrapolated frames); pixels shifted in from outside are empty."""
    dy, dx = shift
    pixels = bytearray(CROP * CROP)
    for r in range(CROP):
        sr = r - dy
        if not 0 <= sr < CROP:
            continue
        base = sr * CROP
        row = r * CROP
        for c in range(CROP):
            sc = c - dx
            if 0 <= sc < CROP:
                v = crop[base + sc]
                if v >= LEVELS[0]:
                    pixels[row + c] = _level(v)
    return _png(CROP, CROP, bytes(pixels))


def render_frames(frames: list[Frame], motion: tuple[float, float] | None, forecast_minutes: int = FORECAST_MINUTES) -> list[dict]:
    """The loop for the card: the kept frames, then frames extrapolated
    along the motion every five minutes. Runs in the executor."""
    out: list[dict] = []
    for fr in frames:
        out.append({"ts": fr.ts.isoformat(), "kind": "past", "offset_min": 0, "png": base64.b64encode(render_png(fr.crop)).decode()})
    if frames and motion is not None and (abs(motion[0]) + abs(motion[1])) > 0.02:
        last = frames[-1]
        for minutes in range(5, forecast_minutes + 1, 5):
            shift = (int(round(motion[0] * minutes)), int(round(motion[1] * minutes)))
            out.append({"ts": (last.ts + timedelta(minutes=minutes)).isoformat(), "kind": "forecast", "offset_min": minutes, "png": base64.b64encode(render_png(last.crop, shift)).decode()})
    return out


# --- coordinator ---------------------------------------------------------------


class RadarCoordinator(DataUpdateCoordinator[RadarData]):
    """The newest radar frames around the entry's point."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, account=None) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} radar", update_interval=UPDATE_INTERVAL, config_entry=entry)
        self.entry = entry
        self.lat = float(entry.data[CONF_POINT_LAT])
        self.lon = float(entry.data[CONF_POINT_LON])
        self.row, self.col = pixel_of(self.lat, self.lon)
        self._frames: deque[Frame] = deque(maxlen=HISTORY_MINUTES // 5 + 1)
        self._account = account
        self._warned = False
        self._missing: set[datetime] = set()  # slots that were 404 (not published)
        self._backfill: asyncio.Task | None = None
        if not (0 <= self.row < ROWS and 0 <= self.col < COLS):
            raise ValueError("point outside the radar composite")

    # geometry of the crop for the card: left edge and top edge in LV95 km
    @property
    def origin_km(self) -> tuple[float, float]:
        return ((X0 + (self.col - CROP_RADIUS) * _PIXEL_M) / 1000, (Y0 - (self.row - CROP_RADIUS) * _PIXEL_M) / 1000)

    @property
    def frames(self) -> list[Frame]:
        return list(self._frames)

    async def _fetch(self, session: aiohttp.ClientSession, ts: datetime) -> bytes | None:
        async with session.get(frame_url(ts), headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT) as resp:
            if resp.status == 404:
                return None
            if resp.status != 200:
                raise RadarError(f"radar answered {resp.status}")
            return await resp.read()

    def _add(self, frame: Frame) -> None:
        frames = [fr for fr in self._frames if fr.ts != frame.ts] + [frame]
        frames.sort(key=lambda fr: fr.ts)
        self._frames = deque(frames[-self._frames.maxlen:], maxlen=self._frames.maxlen)

    async def _load(self, session: aiohttp.ClientSession, ts: datetime) -> bool:
        """Fetch and keep one slot; False if it is not published."""
        if ts in self._missing or any(fr.ts == ts for fr in self._frames):
            return any(fr.ts == ts for fr in self._frames)
        raw = await self._fetch(session, ts)
        if self._account is not None:
            self._account(1, len(raw) if raw else 0)
        if raw is None:
            self._missing.add(ts)
            return False
        crop = await self.hass.async_add_executor_job(decode_crop, raw, self.row, self.col)
        self._add(Frame(ts=ts, crop=crop))
        return True

    async def _async_update_data(self) -> RadarData:
        now = dt_util.utcnow()
        session = async_get_clientsession(self.hass)
        want = slot(now)
        try:
            got = False
            for ts in (want, want - timedelta(minutes=5), want - timedelta(minutes=10)):
                if await self._load(session, ts):
                    got = True
                    break
            if not got and not self._frames:
                raise RadarError("no radar frame for the last 15 minutes")
            newest = self._frames[-1].ts
            await self._load(session, newest - timedelta(minutes=5))  # for the motion estimate
        except (aiohttp.ClientError, TimeoutError, RadarError) as err:
            if self._frames and now - self._frames[-1].ts <= _MAX_AGE:
                if not self._warned:
                    self._warned = True
                    _LOGGER.warning("Radar frame not read, keeping the last one: %s", err)
            else:
                raise UpdateFailed(str(err)) from err
        else:
            self._warned = False
        if now - self._frames[-1].ts > _MAX_AGE:
            raise UpdateFailed(f"newest radar frame is from {self._frames[-1].ts:%H:%M} UTC")
        if self._backfill is None or self._backfill.done():
            self._backfill = self.hass.async_create_background_task(self._fill_history(), f"{DOMAIN} radar history")
        # forget 404 slots older than the history window
        cutoff = now - timedelta(minutes=HISTORY_MINUTES + 10)
        self._missing = {ts for ts in self._missing if ts >= cutoff}
        return await self.hass.async_add_executor_job(analyse, list(self._frames), now)

    async def _fill_history(self) -> None:
        """Fetch the frames of the last two hours that are not held yet, one
        every few seconds, so the loop fills up after a start."""
        session = async_get_clientsession(self.hass)
        newest = self._frames[-1].ts if self._frames else slot(dt_util.utcnow())
        for n in range(2, HISTORY_MINUTES // 5 + 1):
            ts = newest - timedelta(minutes=5 * n)
            if any(fr.ts == ts for fr in self._frames) or ts in self._missing:
                continue
            try:
                await self._load(session, ts)
            except (aiohttp.ClientError, TimeoutError, RadarError) as err:
                _LOGGER.debug("Radar history frame %s not read: %s", ts, err)
                return
            await asyncio.sleep(2)
        self.async_update_listeners()

    async def async_frames_for_card(self) -> dict:
        """Everything the radar card needs: geometry, loop frames as PNGs."""
        data = self.data
        frames = list(self._frames)
        rendered = await self.hass.async_add_executor_job(render_frames, frames, data.motion if data else None)
        e_km, n_km = self.origin_km
        return {
            "size": CROP,
            "km_per_px": 1,
            "origin": {"e_km": e_km, "n_km": n_km},
            "center": {"row": CROP_RADIUS, "col": CROP_RADIUS},
            "levels": list(LEVELS),
            "palette": [list(c) for c in PALETTE],
            "newest": frames[-1].ts.isoformat() if frames else None,
            "motion_kmh": data.speed_kmh if data else None,
            "direction": data.direction if data else None,
            "estimate": "forecast frames are the newest frame moved along the measured motion, not an official nowcast",
            "frames": rendered,
        }

    def latest_png(self) -> bytes | None:
        return render_png(self._frames[-1].crop) if self._frames else None

    @property
    def fresh(self) -> bool:
        return self.data is not None and dt_util.utcnow() - self.data.frame_ts <= _MAX_AGE
