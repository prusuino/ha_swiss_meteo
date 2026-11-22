"""Client for the MeteoSwiss open data files on data.geo.admin.ch.

Two kinds of file are read:

* The local forecast: one CSV per parameter and model run, covering all
  5800 forecast points of Switzerland — 30 to 34 MB for an hourly parameter.
  Downloading them would cost hundreds of megabytes a day, so this module
  reads only the rows of one point with HTTP Range requests. Rows are
  grouped by point in most files (a binary search finds the block in some
  25 small requests, about 40 KB in all) and by timestamp in a few (the
  point's row sits at a fixed position inside every block, so the position
  of the first block predicts all the others). Both layouts are stable per
  parameter; the layout is detected on every read anyway. Where the point
  stood is remembered per parameter (a "hint"): the files of the next run
  are laid out the same way, so the next read goes straight there and
  falls back to the search only when the place no longer fits.
* The 10-minute values of a SwissMetNet station: one small CSV per station.
  The stations of the automatic precipitation network (rain gauges that
  measure nothing else, about as many again) publish the same kind of
  file in a collection of their own, with the same station list layout.

The run of a forecast file is part of its name, so the newest run is found
by probing the current hour and the hours before it with HEAD requests —
no catalogue query is needed. Pure standard library plus aiohttp (which
Home Assistant ships); CSV parsing happens on the few rows that were read.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

from .traffic import note, transferred
from .const import (
    COLLECTION_FORECAST,
    COLLECTION_PRECIP,
    COLLECTION_STATIONS,
    DATA_BASE,
    DATE_MAJOR_PARAMS,
    FORECAST_META_POINTS_URL,
    PRECIP_STATIONS_META_URL,
    STAC_BASE,
    STATIONS_META_URL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

# identity: a compressed transfer would make byte ranges meaningless
_HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
_WHOLE_HEADERS = {"User-Agent": USER_AGENT}  # whole files: let the server compress
_TIMEOUT = aiohttp.ClientTimeout(total=60, sock_connect=15)
_PROBE = 1024  # bytes read per binary-search probe
_WINDOW = 3 * 1024  # bytes read around a predicted row in a date-major file
_SMALL_FILE = 300 * 1024  # below this a single read beats any search
_MAX_PARALLEL = 6  # concurrent Range requests against one file
_MAX_PARALLEL_FILES = 3  # forecast files read at once (each with up to _MAX_PARALLEL ranges)
_MAX_READS = 1000  # Range requests one read of a file may take (the largest take a few hundred)
_DAILY_FILE = 3 * 1024 * 1024  # a file of daily values has 1.3 MB, one of hourly values 30 MB
# Reading at a remembered place. A point's block moves a little from run to
# run (the values before it are written with more or fewer digits): the
# window reaches this far to either side of where the block stood.
_HINT_MARGIN = 8 * 1024
# In a date-major file the point's row sits at nearly the same place in every
# block, and the distance from one block's row to the next changes slowly
# (values gain or lose a digit as the day goes on). Predicted from the two
# distances before it, a row was found within 50 bytes in half of the blocks,
# within 550 bytes in 99 % and within 700 bytes in all (three hourly files of
# 2026-11-22, 220 blocks each). So the first window is 1 KB; the wider ones
# are for the rows it misses.
_ROW_WINDOWS = (1024, 4 * 1024, 64 * 1024)
_ROW_WIDTH = 24  # a row is 20 to 27 bytes: aim the window at its middle
# A read at a remembered place that returns this many rows fewer than last
# time is not trusted: the point is searched for from scratch.
_HINT_ROW_TOLERANCE = 3

# How the published files order their points: by number with the types
# mixed, grouped by type with the numbers compared as text (1, 10, 100,
# 11 …), or grouped by type with the numbers ascending. A search starts
# with the order a few samples of the file agree with and tries the others
# when it comes back empty.
_ORDERS: tuple[Callable[[int, int], tuple[Any, ...]], ...] = (
    lambda pid, ptype: (pid, ptype),
    lambda pid, ptype: (ptype, str(pid)),
    lambda pid, ptype: (ptype, pid),
)


class OgdError(Exception):
    """A file could not be read or made no sense."""


class OgdUnavailable(OgdError):
    """The service answered with an error or did not answer."""


# --- Points and stations -----------------------------------------------------


@dataclass(frozen=True)
class Point:
    """A forecast point: a postal-code centre, a station or a mountain spot."""

    point_type: int
    point_id: int
    name: str
    postal_code: str
    station_abbr: str
    height: float | None
    lat: float
    lon: float

    @property
    def key(self) -> tuple[int, int]:
        return self.point_id, self.point_type


@dataclass(frozen=True)
class Station:
    """A SwissMetNet weather station."""

    abbr: str
    name: str
    canton: str
    height: float | None
    lat: float
    lon: float


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance, good enough to rank stations and points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_csv(body: bytes) -> list[dict[str, str]]:
    """The semicolon-separated, Latin-1 encoded CSV MeteoSwiss publishes."""
    text = body.decode("latin-1")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


async def _fetch(session: aiohttp.ClientSession, url: str) -> bytes:
    """A whole small file. Unlike the range reads it may come compressed (a
    station file is 16 KB plain, 4 KB on the wire); the size reported to the
    traffic counter is what was transferred."""
    try:
        async with session.get(url, headers=_WHOLE_HEADERS, timeout=_TIMEOUT) as resp:
            if resp.status != 200:
                note(1, 0)
                raise OgdUnavailable(f"HTTP {resp.status} for {url.rsplit('/', 1)[-1]}")
            body = await resp.read()
            note(1, transferred(resp.headers, body))
            return body
    except (TimeoutError, aiohttp.ClientError) as err:
        raise OgdUnavailable(f"{type(err).__name__} for {url.rsplit('/', 1)[-1]}") from err


async def async_fetch_points(session: aiohttp.ClientSession) -> list[Point]:
    """All forecast points with their coordinates (about 800 KB, read at setup)."""
    rows = _parse_csv(await _fetch(session, FORECAST_META_POINTS_URL))
    points: list[Point] = []
    for row in rows:
        try:
            lat, lon = float(row["point_coordinates_wgs84_lat"]), float(row["point_coordinates_wgs84_lon"])
            points.append(
                Point(
                    point_type=int(row["point_type_id"]),
                    point_id=int(row["point_id"]),
                    name=row.get("point_name", "").strip(),
                    postal_code=row.get("postal_code", "").strip(),
                    station_abbr=row.get("station_abbr", "").strip(),
                    height=_float(row.get("point_height_masl")),
                    lat=lat,
                    lon=lon,
                )
            )
        except (KeyError, ValueError):
            continue
    if not points:
        raise OgdError("the forecast point list is empty")
    return points


async def _async_fetch_station_list(session: aiohttp.ClientSession, url: str) -> list[Station]:
    rows = _parse_csv(await _fetch(session, url))
    stations: list[Station] = []
    for row in rows:
        try:
            stations.append(
                Station(
                    abbr=row["station_abbr"].strip(),
                    name=row.get("station_name", "").strip(),
                    canton=row.get("station_canton", "").strip(),
                    height=_float(row.get("station_height_masl")),
                    lat=float(row["station_coordinates_wgs84_lat"]),
                    lon=float(row["station_coordinates_wgs84_lon"]),
                )
            )
        except (KeyError, ValueError):
            continue
    if not stations:
        raise OgdError("the station list is empty")
    return stations


async def async_fetch_stations(session: aiohttp.ClientSession) -> list[Station]:
    """All SwissMetNet stations with their coordinates."""
    return await _async_fetch_station_list(session, STATIONS_META_URL)


async def async_fetch_precip_stations(session: aiohttp.ClientSession) -> list[Station]:
    """All stations of the automatic precipitation network with their
    coordinates. Their abbreviations do not occur among the SwissMetNet
    stations: a weather station is not listed here a second time."""
    return await _async_fetch_station_list(session, PRECIP_STATIONS_META_URL)


def nearest(items, lat: float, lon: float, count: int = 3):
    """The `count` items closest to a location, with their distance in km."""
    ranked = sorted(((distance_km(lat, lon, i.lat, i.lon), i) for i in items), key=lambda x: x[0])
    return ranked[:count]


# --- Station measurements ----------------------------------------------------


def station_now_url(abbr: str) -> str:
    a = abbr.lower()
    return f"{DATA_BASE}/{COLLECTION_STATIONS}/{a}/ogd-smn_{a}_t_now.csv"


def precip_now_url(abbr: str) -> str:
    a = abbr.lower()
    return f"{DATA_BASE}/{COLLECTION_PRECIP}/{a}/ogd-smn-precip_{a}_t_now.csv"


@dataclass
class StationReading:
    """The newest 10-minute row of a station."""

    abbr: str
    timestamp: datetime
    values: dict[str, float | None]


def _parse_station_timestamp(value: str) -> datetime:
    # "07.11.2026 16:50", UTC
    return datetime.strptime(value.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=UTC)


async def _async_fetch_reading(session: aiohttp.ClientSession, abbr: str, url: str) -> StationReading:
    rows = _parse_csv(await _fetch(session, url))
    if not rows:
        raise OgdError(f"station file of {abbr} has no rows")
    row = rows[-1]
    try:
        ts = _parse_station_timestamp(row["reference_timestamp"])
    except (KeyError, ValueError) as err:
        raise OgdError(f"station file of {abbr}: bad timestamp") from err
    values = {k: _float(v) for k, v in row.items() if k not in ("station_abbr", "reference_timestamp")}
    return StationReading(abbr=abbr, timestamp=ts, values=values)


async def async_fetch_station_reading(session: aiohttp.ClientSession, abbr: str) -> StationReading:
    """The last complete row of the station's 10-minute file (today's values)."""
    return await _async_fetch_reading(session, abbr, station_now_url(abbr))


async def async_fetch_precip_reading(session: aiohttp.ClientSession, abbr: str) -> StationReading:
    """The last row of a precipitation station's 10-minute file: its one
    value, the precipitation of the last ten minutes."""
    return await _async_fetch_reading(session, abbr, precip_now_url(abbr))


# --- Forecast runs -----------------------------------------------------------


def forecast_file_url(run: datetime, param: str) -> str:
    """The file of one parameter of one model run (run in UTC, whole hour)."""
    day = run.strftime("%Y%m%d")
    stamp = run.strftime("%Y%m%d%H%M")
    return f"{DATA_BASE}/{COLLECTION_FORECAST}/{day}-ch/vnut12.lssw.{stamp}.{param}.csv"


async def _head_size(session: aiohttp.ClientSession, url: str) -> int | None:
    """The file's size, or None when it does not exist (yet). A HEAD
    answer without Content-Length is followed by a one-byte range request,
    whose Content-Range names the total."""
    name = url.rsplit("/", 1)[-1]
    try:
        async with session.head(url, headers=_HEADERS, timeout=_TIMEOUT) as resp:
            if resp.status in (403, 404):
                return None
            if resp.status != 200:
                raise OgdUnavailable(f"HTTP {resp.status} for {name}")
            if resp.headers.get("Content-Length"):
                return int(resp.headers["Content-Length"])
        async with session.get(url, headers={**_HEADERS, "Range": "bytes=0-0"}, timeout=_TIMEOUT) as resp:
            if resp.status in (403, 404):
                return None
            total = resp.headers.get("Content-Range", "").rsplit("/", 1)[-1]
            if resp.status == 206 and total.isdigit():
                return int(total)
            if resp.status == 200 and resp.headers.get("Content-Length"):
                return int(resp.headers["Content-Length"])
            raise OgdUnavailable(f"no size for {name} (HTTP {resp.status})")
    except (TimeoutError, aiohttp.ClientError) as err:
        raise OgdUnavailable(f"{type(err).__name__} for {name}") from err


async def async_find_latest_run(
    session: aiohttp.ClientSession, now: datetime, probe_param: str = "jp2000d0", max_back: int = 6
) -> datetime | None:
    """The newest run whose files exist, trying the current hour and the
    hours before it. None when none of them exists (an outage, or a gap
    longer than `max_back` hours)."""
    start = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    for back in range(max_back + 1):
        run = start - timedelta(hours=back)
        if await _head_size(session, forecast_file_url(run, probe_param)) is not None:
            return run
    return None


async def async_catalogue_latest_run(session: aiohttp.ClientSession) -> datetime | None:
    """Fallback discovery through the STAC catalogue, should the file-name
    pattern ever change: the newest run named in the newest day's item."""
    body = await _fetch(session, f"{STAC_BASE}/{COLLECTION_FORECAST}/items?limit=3")
    import json

    try:
        items = json.loads(body)["features"]
    except (ValueError, KeyError) as err:
        raise OgdError("STAC answer is not what was expected") from err
    runs: list[datetime] = []
    for item in items:
        for key in item.get("assets", {}):
            parts = key.split(".")
            if len(parts) >= 4 and len(parts[2]) == 12 and parts[2].isdigit():
                runs.append(datetime.strptime(parts[2], "%Y%m%d%H%M").replace(tzinfo=UTC))
    return max(runs) if runs else None


# --- Reading one point out of a forecast file --------------------------------


@dataclass
class ReadStats:
    """What a read cost — shown as diagnostics so the traffic stays visible."""

    requests: int = 0
    bytes: int = 0


class _RangeFile:
    def __init__(self, session: aiohttp.ClientSession, url: str, size: int, stats: ReadStats) -> None:
        self._session = session
        self._url = url
        self.size = size
        self.stats = stats
        self._sem = asyncio.Semaphore(_MAX_PARALLEL)
        self._reads = 0

    async def read(self, start: int, length: int) -> bytes:
        start = max(0, start)
        end = min(self.size - 1, start + length - 1)
        if end < start:
            return b""
        # The budget of one read: a search that does not end must fail,
        # not turn into a stream of requests against the open-data host.
        self._reads += 1
        if self._reads > _MAX_READS:
            raise OgdError(f"too many requests for {self._url.rsplit('/', 1)[-1]}")
        headers = {**_HEADERS, "Range": f"bytes={start}-{end}"}
        async with self._sem:
            try:
                async with self._session.get(self._url, headers=headers, timeout=_TIMEOUT) as resp:
                    if resp.status not in (200, 206):
                        raise OgdUnavailable(f"HTTP {resp.status} for {self._url.rsplit('/', 1)[-1]}")
                    body = await resp.read()
            except (TimeoutError, aiohttp.ClientError) as err:
                raise OgdUnavailable(f"{type(err).__name__} for {self._url.rsplit('/', 1)[-1]}") from err
        self.stats.requests += 1
        self.stats.bytes += len(body)
        if len(body) > end - start + 1:
            # The server ignored the range and sent everything: use the slice.
            body = body[start : end + 1]
        return body


def _key(line: bytes) -> tuple[int, int, str] | None:
    """(point_id, point_type_id, timestamp) of a data row; None for the header."""
    parts = line.split(b";")
    if len(parts) < 4:
        return None
    try:
        return int(parts[0]), int(parts[1]), parts[2].decode()
    except ValueError:
        return None


def _rows_of(chunk: bytes, chunk_offset: int, point: tuple[int, int], at_start: bool) -> list[tuple[int, bytes]]:
    """(absolute offset, line) of every complete row of `point` in a chunk."""
    out: list[tuple[int, bytes]] = []
    pos = 0
    if not at_start:
        nl = chunk.find(b"\n")
        if nl < 0:
            return out
        pos = nl + 1
    while True:
        end = chunk.find(b"\n", pos)
        if end < 0:
            break
        line = chunk[pos:end].rstrip(b"\r")
        k = _key(line)
        if k and (k[0], k[1]) == point:
            out.append((chunk_offset + pos, line))
        pos = end + 1
    return out


async def _row_at(rf: _RangeFile, offset: int) -> tuple[tuple[int, int, str] | None, int]:
    """The first complete data row at or after `offset`, with its offset."""
    chunk = await rf.read(offset, _PROBE)
    pos = 0
    if offset > 0:
        nl = chunk.find(b"\n")
        if nl < 0:
            chunk = await rf.read(offset, _PROBE * 8)
            nl = chunk.find(b"\n")
            if nl < 0:
                return None, offset
        pos = nl + 1
    for _ in range(3):  # skip the header line and the odd short row
        end = chunk.find(b"\n", pos)
        if end < 0:
            return None, offset + pos
        k = _key(chunk[pos:end].rstrip(b"\r"))
        if k is not None:
            return k, offset + pos
        pos = end + 1
    return None, offset + pos


async def _read_point_major(rf: _RangeFile, point: tuple[int, int], lo: int = 0, hi: int | None = None) -> list[bytes]:
    return [line for _off, line in await _find_point_block(rf, point, lo, hi)]


def _block_hint(rows: list[tuple[int, bytes]], size: int) -> dict[str, int]:
    """Where a point's block stood: offset, length, file size, row count."""
    first, (last_off, last_line) = rows[0][0], rows[-1]
    return {"o": first, "n": last_off + len(last_line) + 1 - first, "s": size, "c": len(rows)}


def _hint_ok(hint: Any, *keys: str) -> bool:
    return isinstance(hint, dict) and all(isinstance(hint.get(key), int) and hint[key] >= 0 for key in keys) and hint.get("s", 0) > 0


async def _read_hinted_block(rf: _RangeFile, point: tuple[int, int], hint: dict[str, int]) -> list[tuple[int, bytes]]:
    """The point's rows in a point-major file, read at the place they had in
    the last run (moved in proportion when the file has another size).
    Empty when they are not there or fewer than last time."""
    centre = hint["o"] * rf.size // hint["s"]
    start = max(0, centre - _HINT_MARGIN)
    length = hint["n"] + 2 * _HINT_MARGIN
    rows: list[tuple[int, bytes]] = []
    for _ in range(4):
        chunk = await rf.read(start, length)
        rows = _rows_of(chunk, start, point, start == 0)
        if not rows:
            return []
        first_off, last_off = rows[0][0], rows[-1][0]
        touches_start = start > 0 and first_off - start < 64
        touches_end = start + length < rf.size and start + length - last_off < 128
        if not touches_start and not touches_end:
            break
        if touches_start:
            start = max(0, start - _HINT_MARGIN)
            length += _HINT_MARGIN
        if touches_end:
            length += _HINT_MARGIN
    else:
        return []  # still at the edge of the window: let the search settle it
    if len(rows) < hint["c"] - _HINT_ROW_TOLERANCE:
        return []
    return rows


async def _find_point_block(
    rf: _RangeFile, point: tuple[int, int], lo: int = 0, hi: int | None = None
) -> list[tuple[int, bytes]]:
    """The rows of the point between `lo` and `hi` (the whole file by
    default), where all rows of a point stand together and the points
    are sorted — how, differs from file to file (see `_ORDERS`). A dozen
    samples show which orders the file can have; the search runs with
    the one that fits best and with the others when it finds nothing."""
    hi = rf.size if hi is None else hi
    probes = 12
    results = await asyncio.gather(*(_row_at(rf, lo + i * (hi - lo) // probes) for i in range(probes)))
    samples = sorted((off, k) for k, off in results if k and off < hi)

    def breaks(order: Callable[[int, int], tuple[Any, ...]]) -> int:
        keys = [order(k[0], k[1]) for _off, k in samples]
        return sum(1 for one, two in zip(keys, keys[1:]) if two < one)

    for order in sorted(_ORDERS, key=breaks):
        rows = await _search_point_block(rf, point, lo, hi, order, samples)
        if rows:
            return rows
    return []


async def _search_point_block(
    rf: _RangeFile,
    point: tuple[int, int],
    span_lo: int,
    span_hi: int,
    order: Callable[[int, int], tuple[Any, ...]],
    samples: list[tuple[int, tuple[int, int, str]]],
) -> list[tuple[int, bytes]]:
    """Binary search for the point's rows in a span sorted by `order`:
    the samples narrow the span, the bisection does the rest. Empty when
    the point is not where this order puts it."""
    target = order(*point)
    lo, hi = span_lo, span_hi
    found: int | None = None
    for off, k in samples:
        if (k[0], k[1]) == point:
            found = off
            break
        if order(k[0], k[1]) < target:
            lo = max(lo, off)
        else:
            hi = min(hi, off)
    for _ in range(48):
        if found is not None or hi - lo <= 2 * _PROBE:
            break
        mid = (lo + hi) // 2
        k, off = await _row_at(rf, mid)
        if k is None or off >= hi:
            hi = mid
        elif (k[0], k[1]) == point:
            found = off
        elif order(k[0], k[1]) < target:
            lo = off
        else:
            hi = mid
    centre = found if found is not None else lo
    start, length = max(span_lo, centre - 8 * _PROBE), 16 * _PROBE
    rows: list[tuple[int, bytes]] = []
    for _ in range(8):
        chunk = await rf.read(start, min(length, span_hi + 2 * _PROBE - start))
        rows = [r for r in _rows_of(chunk, start, point, start == 0) if r[0] < span_hi]
        if not rows:
            return []
        first_off, last_off = rows[0][0], rows[-1][0]
        touches_start = start > span_lo and first_off - start < 64
        touches_end = start + length < span_hi and start + length - last_off < 128
        if not touches_start and not touches_end:
            break
        if touches_start:
            start = max(0, start - 8 * _PROBE)
            length += 8 * _PROBE
        if touches_end:
            length += 8 * _PROBE
    return rows


async def _date_samples(rf: _RangeFile, probes: int) -> list[tuple[int, str]]:
    """(offset, timestamp) at evenly spaced offsets, sorted by offset."""
    results = await asyncio.gather(*(_row_at(rf, i * rf.size // probes) for i in range(probes)))
    return sorted((off, k[2]) for k, off in results if k)


async def _date_boundary(rf: _RangeFile, lo: int, hi: int, date_after: str) -> int:
    """The offset where the rows of `date_after` begin, between an offset
    `lo` that lies in the previous timestamp block and `hi` in this one."""
    for _ in range(40):
        if hi - lo <= _PROBE:
            break
        mid = (lo + hi) // 2
        k, off = await _row_at(rf, mid)
        if k is None or k[2] >= date_after:
            hi = mid
        else:
            lo = off
    chunk = await rf.read(lo, hi - lo + 4 * _PROBE)
    pos = chunk.find(b"\n") + 1 if lo > 0 else 0
    while pos < len(chunk):
        end = chunk.find(b"\n", pos)
        if end < 0:
            break
        k = _key(chunk[pos:end].rstrip(b"\r"))
        if k and k[2] >= date_after:
            return lo + pos
        pos = end + 1
    return hi


async def _read_date_major_small(rf: _RangeFile, point: tuple[int, int]) -> list[bytes]:
    """Date-major file with a handful of timestamp blocks (the daily
    temperature files): find the point's row in the first block by
    search, then read a small window at the predicted position in each
    later block, one block at a time, correcting the step with every hit.
    Costs about 80 KB where reading the file would cost 1.3 MB."""
    samples = await _date_samples(rf, 12)
    dates = sorted({d for _o, d in samples})
    if len(dates) < 2:
        return await _read_whole(rf, point)
    lo = max(o for o, d in samples if d == dates[0])
    hi = min(o for o, d in samples if d == dates[1])
    first_end = await _date_boundary(rf, lo, hi, dates[1])
    rows = await _find_point_block(rf, point, 0, first_end)
    if not rows:
        # Not where the block's order puts it; the caller reads the file whole.
        return []
    out = [line for _off, line in rows]
    last_hit = rows[0][0]
    step = first_end
    for _ in range(len(dates) - 1):
        # The blocks differ a little in length: for the last points of a
        # block the prediction may lie past the end of the file.
        predicted = min(last_hit + step, rf.size - 1)
        hit = None
        for window in (4 * 1024, 24 * 1024):
            start = max(0, predicted - window // 2)
            chunk = await rf.read(start, window)
            found = [r for r in _rows_of(chunk, start, point, start == 0) if r[0] > last_hit]
            if found:
                hit = found[0]
                break
        if hit is None:
            return await _read_block_search(rf, point)
        out.append(hit[1])
        step = hit[0] - last_hit
        last_hit = hit[0]
    return out


async def _read_block_search(rf: _RangeFile, point: tuple[int, int]) -> list[bytes]:
    """Date-major file with few timestamp blocks (the daily files): find
    every block's start by bisecting on the timestamp, then search the
    point inside each block the way a point-major file is searched."""
    samples = await _date_samples(rf, 36)
    dates = sorted({d for _o, d in samples})
    starts: dict[str, int] = {dates[0]: 0}
    bounds: list[tuple[str, int, int]] = []
    for prev, nxt in zip(dates, dates[1:]):
        lo = max(o for o, d in samples if d == prev)
        hi = min(o for o, d in samples if d == nxt)
        bounds.append((nxt, lo, hi))
    found = await asyncio.gather(*(_date_boundary(rf, lo, hi, d) for d, lo, hi in bounds))
    for (d, _lo, _hi), off in zip(bounds, found):
        starts[d] = off
    ordered = [starts[d] for d in dates] + [rf.size]
    blocks = await asyncio.gather(
        *(_read_point_major(rf, point, lo=ordered[i], hi=ordered[i + 1]) for i in range(len(dates)))
    )
    rows: list[bytes] = []
    for block_rows in blocks:
        rows.extend(block_rows)
    return rows


async def _date_major_start(rf: _RangeFile, point: tuple[int, int]) -> tuple[list[tuple[int, bytes]], int]:
    """Read the first half megabyte whole: the point's rows in the first
    blocks with their offsets, and the block length. The first block can be
    short (a run starts with a partial hour), so the block length is taken
    from a later pair."""
    head = await rf.read(0, 512 * 1024)
    lines = head.split(b"\n")
    offset = 0
    block_starts: list[int] = []
    current_date: str | None = None
    found: list[tuple[int, bytes]] = []
    for line in lines[:-1]:
        k = _key(line.rstrip(b"\r"))
        if k:
            if k[2] != current_date:
                current_date = k[2]
                block_starts.append(offset)
            if (k[0], k[1]) == point:
                found.append((offset, line.rstrip(b"\r")))
        offset += len(line) + 1
    if not found or len(block_starts) < 2:
        raise OgdError("point not found in the first blocks of a date-major file")
    if len(block_starts) >= 3:
        step = block_starts[-1] - block_starts[-2]
    else:
        step = block_starts[1] - block_starts[0]
    return found, step


async def _row_near(rf: _RangeFile, point: tuple[int, int], predicted: int, beyond: int) -> tuple[int, bytes] | None:
    """The point's first row after `beyond` around a predicted offset: a
    small window first, wider ones when it is not in there."""
    for window in _ROW_WINDOWS:
        start = max(0, predicted + _ROW_WIDTH // 2 - window // 2)
        chunk = await rf.read(start, window)
        # Only a row beyond the last one counts: a window that still covers
        # an earlier row must not send the read back to it.
        found = [r for r in _rows_of(chunk, start, point, start == 0) if r[0] > beyond]
        if found:
            return found[0]
    return None


async def _read_date_major(rf: _RangeFile, point: tuple[int, int], hint: dict[str, int] | None = None) -> tuple[list[bytes], dict[str, int]]:
    """Date-major file with many blocks (the hourly files): one row of the
    point per block, a block length apart. The rows are read one block at a
    time, each at the offset the rows before it predict (see `_ROW_WINDOWS`).

    Where to begin comes from the last run (`hint`: the offset of the first
    row and the first two distances) or from reading the head of the file.
    Returns the rows and the hint for the next run."""
    rows: list[tuple[int, bytes]] = []
    seeds: list[int] = []  # distances to use while the rows read so far cannot predict
    if hint is not None and hint["o"] < hint["d"] + _ROW_WINDOWS[1]:
        first = await _row_near(rf, point, hint["o"], -1)
        # a row found far from where the first one stood belongs to a later block
        if first is not None and abs(first[0] - hint["o"]) < _ROW_WINDOWS[1]:
            rows = [first]
            seeds = [hint["d"], hint["t"]]
    if not rows:
        rows, step = await _date_major_start(rf, point)
        seeds = [step, step, step]
    strikes = 0
    virtual = rows[-1][0]  # where the read stands; runs ahead of the last row after a miss
    while strikes < 4:
        n = len(rows)
        if strikes == 0 and n >= 4:
            # the last distance, corrected by how the distance changed
            last, before = rows[-1][0] - rows[-2][0], rows[-2][0] - rows[-3][0]
            step = 2 * last - before
        elif strikes == 0 and n - 1 < len(seeds):
            step = seeds[n - 1]
        elif n >= 2 and (n >= 3 or len(seeds) < 2):
            step = rows[-1][0] - rows[-2][0]
        else:
            step = seeds[-1]
        predicted = virtual + step
        if step <= 0 or predicted >= rf.size:
            break
        hit = await _row_near(rf, point, predicted, rows[-1][0])
        if hit is None:
            # a block without the point, or the end of what the file holds
            strikes += 1
            virtual = predicted
            continue
        strikes = 0
        rows.append(hit)
        virtual = hit[0]
    offsets = [off for off, _line in rows]
    distance = offsets[1] - offsets[0] if len(offsets) > 1 else seeds[0]
    regular = offsets[2] - offsets[1] if len(offsets) > 2 else seeds[-1]
    new_hint = {"o": offsets[0], "d": distance, "t": regular, "s": rf.size, "c": len(rows)}
    return [line for _off, line in rows], new_hint


async def _read_whole(rf: _RangeFile, point: tuple[int, int]) -> list[bytes]:
    chunk = await rf.read(0, rf.size)
    return [line for _off, line in _rows_of(chunk, 0, point, True)]


def _parse_rows(rows: list[bytes]) -> list[tuple[datetime, float | None]]:
    out: list[tuple[datetime, float | None]] = []
    for line in rows:
        parts = line.split(b";")
        if len(parts) < 4:
            continue
        try:
            ts = datetime.strptime(parts[2].decode(), "%Y%m%d%H%M").replace(tzinfo=UTC)
        except ValueError:
            continue
        out.append((ts, _float(parts[3].decode("latin-1"))))
    out.sort(key=lambda x: x[0])
    return out


async def async_read_point(
    session: aiohttp.ClientSession,
    url: str,
    point: tuple[int, int],
    param: str,
    stats: ReadStats,
    hints: dict[str, Any] | None = None,
) -> list[tuple[datetime, float | None]]:
    """The (timestamp, value) rows of one point in one forecast file.

    `hints` maps a parameter to where the point stood in its file the last
    time (see the module text). A fitting entry is used and renewed; one
    that no longer fits is replaced by what the search finds."""
    size = await _head_size(session, url)
    stats.requests += 1
    if size is None:
        raise OgdUnavailable(f"missing file {url.rsplit('/', 1)[-1]}")
    rf = _RangeFile(session, url, size, stats)
    hint = hints.get(param) if hints is not None else None
    new_hint: dict[str, int] | None = None
    if size <= _SMALL_FILE:
        rows = await _read_whole(rf, point)
    elif param in DATE_MAJOR_PARAMS:
        # Few blocks (daily values): search each block; many (hourly): predict.
        if size <= _DAILY_FILE:
            rows = await _read_date_major_small(rf, point) or await _read_whole(rf, point)
        else:
            trusted = hint if _hint_ok(hint, "o", "d", "t", "c") else None
            rows, new_hint = await _read_date_major(rf, point, trusted)
            if trusted is not None and len(rows) < trusted["c"] - _HINT_ROW_TOLERANCE:
                # fewer rows than last time from the remembered place: read from scratch
                rows, new_hint = await _read_date_major(rf, point)
    else:
        found = await _read_hinted_block(rf, point, hint) if _hint_ok(hint, "o", "n", "c") else []
        if not found:
            found = await _find_point_block(rf, point)
        rows = [line for _off, line in found]
        if found:
            new_hint = _block_hint(found, size)
        if not rows and size <= _DAILY_FILE:
            # Not where the file's order puts it — a point listed out of
            # order, or a layout that has changed: a file this small is
            # read whole, which finds the point wherever it stands.
            rows = await _read_whole(rf, point)
        elif not rows:
            # The layout may have changed: try the other strategy once.
            rows, new_hint = await _read_date_major(rf, point)
    if not rows:
        raise OgdError(f"point {point[1]}/{point[0]} not in {url.rsplit('/', 1)[-1]}")
    if hints is not None:
        if new_hint is not None:
            hints[param] = new_hint
        else:
            hints.pop(param, None)
    return _parse_rows(rows)


@dataclass
class ForecastData:
    """One point's values of one model run."""

    run: datetime
    point: tuple[int, int]
    series: dict[str, list[tuple[datetime, float | None]]] = field(default_factory=dict)
    stats: ReadStats = field(default_factory=ReadStats)
    missing: list[str] = field(default_factory=list)


async def async_fetch_forecast(
    session: aiohttp.ClientSession,
    run: datetime,
    point: tuple[int, int],
    params: tuple[str, ...],
    hints: dict[str, Any] | None = None,
) -> ForecastData:
    """All requested parameters of a run for a point. A parameter whose
    file is missing or unreadable is listed in `missing` rather than
    failing the whole fetch; the entities then show what there is.
    `hints` is the caller's memory of where the point stood (see
    `async_read_point`); it is updated in place."""
    data = ForecastData(run=run, point=point)
    limit = asyncio.Semaphore(_MAX_PARALLEL_FILES)

    async def one(param: str) -> None:
        try:
            async with limit:
                data.series[param] = await async_read_point(session, forecast_file_url(run, param), point, param, data.stats, hints)
        except OgdError as err:
            _LOGGER.debug("Forecast %s for %s not read: %s", param, point, err)
            data.missing.append(param)

    await asyncio.gather(*(one(p) for p in params))
    if not data.series:
        raise OgdUnavailable(f"no forecast file of run {run:%Y-%m-%d %H:%M} could be read")
    return data
