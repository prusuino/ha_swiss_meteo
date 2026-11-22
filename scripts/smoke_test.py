"""Smoke test against the real sources.

The test suite works on files kept in the repository, so it stays green when
MeteoSwiss, MeteoAlarm or Open-Meteo change what they publish. This script
reads every feed once with the integration's own readers and fails when one
of them no longer delivers what the integration expects. The "Smoke test"
workflow runs it once a week; run it by hand with

    python scripts/smoke_test.py

It reads for Zurich (a place everyone may know), prints what each read
cost, and exits with 1 if a check failed. About 40 requests, a few MB.
"""
from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.swiss_meteo import meteoalarm, ogd, open_meteo, pollen, radar
from custom_components.swiss_meteo.const import (
    DAILY_COMPANION_PARAMS,
    DAILY_PARAMS,
    EXTENDED_PARAMS,
    HOURLY_PARAMS,
)
from custom_components.swiss_meteo.traffic import metered

LAT, LON = 47.3769, 8.5417
POINT = (800100, 2)  # 8001 Zürich, postal-code centre
STATION, POLLEN_STATION = "SMA", "PZH"


class Cost:
    """Requests and bytes of one check."""

    def __init__(self) -> None:
        self.requests = 0
        self.bytes = 0

    def __call__(self, requests: int, nbytes: int) -> None:
        self.requests += requests
        self.bytes += nbytes


def need(condition: bool, what: str) -> None:
    if not condition:
        raise AssertionError(what)


async def check_forecast(session: aiohttp.ClientSession, cost: Cost) -> str:
    now = datetime.now(UTC)
    run = await ogd.async_find_latest_run(session, now) or await ogd.async_catalogue_latest_run(session)
    need(run is not None, "no forecast run found")
    need(now - run < timedelta(hours=12), f"newest run is from {run:%Y-%m-%d %H:%M} UTC")
    said = []
    for label, params, least in (
        ("daily", DAILY_PARAMS, 6),
        ("days from hours", DAILY_COMPANION_PARAMS, 48),
        ("hourly", HOURLY_PARAMS, 48),
        ("extended", EXTENDED_PARAMS, 48),
    ):
        data = await ogd.async_fetch_forecast(session, run, POINT, params)
        cost(data.stats.requests, data.stats.bytes)
        need(not data.missing, f"{label}: parameters not read: {data.missing}")
        shortest = min(len(data.series[param]) for param in params)
        need(shortest >= least, f"{label}: only {shortest} rows")
        said.append(f"{label} {shortest}+ rows ({data.stats.bytes // 1024} KB)")
    return f"run {run:%H:%M} UTC, " + ", ".join(said)


async def check_station(session: aiohttp.ClientSession, cost: Cost) -> str:
    with metered(cost):
        reading = await ogd.async_fetch_station_reading(session, STATION)
        # the gauges come and go: take the one nearest to the test place
        _km, nearest = ogd.nearest(await ogd.async_fetch_precip_stations(session), LAT, LON, 1)[0]
        gauge = await ogd.async_fetch_precip_reading(session, nearest.abbr)
    need(datetime.now(UTC) - reading.timestamp < timedelta(minutes=45), f"station row is from {reading.timestamp}")
    need(reading.values.get("tre200s0") is not None, "station has no temperature")
    need("rre150z0" in gauge.values, "rain gauge has no precipitation column")
    return f"{STATION} {reading.values['tre200s0']} °C at {reading.timestamp:%H:%M} UTC, gauge {nearest.abbr} read"


async def check_lists(session: aiohttp.ClientSession, cost: Cost) -> str:
    with metered(cost):
        points = await ogd.async_fetch_points(session)
        stations = await ogd.async_fetch_stations(session)
        gauges = await ogd.async_fetch_precip_stations(session)
        pollen_stations = await pollen.async_fetch_pollen_stations(session)
    need(len(points) > 3000, f"only {len(points)} forecast points")
    need(any((p.point_id, p.point_type) == POINT for p in points), "the test point is gone from the point list")
    need(len(stations) > 100 and len(gauges) > 50 and len(pollen_stations) > 10, "a station list is nearly empty")
    return f"{len(points)} points, {len(stations)} stations, {len(gauges)} gauges, {len(pollen_stations)} pollen stations"


async def check_pollen(session: aiohttp.ClientSession, cost: Cost) -> str:
    with metered(cost):
        reading = await pollen.async_fetch_pollen_reading(session, POLLEN_STATION)
    need(len(reading.current) == 7, f"{len(reading.current)} pollen species instead of 7")
    return f"{POLLEN_STATION}: 7 species, {reading.hours} hours of today"


async def check_warnings(session: aiohttp.ClientSession, cost: Cost) -> str:
    headers = meteoalarm._HEADERS
    timeout = aiohttp.ClientTimeout(total=120)
    async with session.head(meteoalarm.WARNINGS_URL, headers=headers, timeout=timeout) as resp:
        cost(1, 0)
        need(resp.status == 200, f"HEAD answered {resp.status}")
        length = resp.headers.get("Content-Length")
    async with session.get(meteoalarm.WARNINGS_URL, headers=headers, timeout=timeout) as resp:
        need(resp.status == 200, f"feed answered {resp.status}")
        body = await resp.read()
        cost(1, len(body))
    entries = meteoalarm.parse_feed(body)
    need(length is not None, "the feed no longer states its length: it would be read hourly only")
    said = f"{len(entries)} alerts in {len(body) // 1024} KB"
    if not entries:
        return said + " (none in force, alert documents not checked)"
    need(all(entry.cap_url for entry in entries), "an alert has no link to its document")
    need(sum(1 for entry in entries if entry.rings) >= len(entries) * 0.9, "most alerts carry no polygon")
    async with session.get(entries[0].cap_url, headers=headers, timeout=timeout) as resp:
        need(resp.status == 200, f"alert document answered {resp.status}")
        document = await resp.read()
        cost(1, len(document))
    alert = meteoalarm.parse_cap(document)
    info = alert["info"][0] if alert["info"] else {}
    need(alert.get("identifier") == entries[0].identifier, "alert document and feed entry name different alerts")
    need(len(alert["info"]) >= 4, f"alert in {len(alert['info'])} languages only")
    need(any(p["valueName"] == "awareness_level" for p in info.get("parameter", [])), "alert without awareness level")
    here = meteoalarm.covering(entries, LAT, LON, datetime.now(UTC))
    return said + f", {len(here)} cover the test place, alert document {len(document) // 1024} KB in {len(alert['info'])} languages"


async def check_radar(session: aiohttp.ClientSession, cost: Cost) -> str:
    now = datetime.now(UTC)
    newest = radar.slot(now)
    row, col = radar.pixel_of(LAT, LON)
    for back in range(4):
        ts = newest - timedelta(minutes=5 * back)
        async with session.get(radar.frame_url(ts), headers={"User-Agent": meteoalarm.USER_AGENT}, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            cost(1, 0)
            if resp.status != 200:
                continue
            raw = await resp.read()
            cost(0, len(raw))
        started = time.perf_counter()
        crop = radar.decode_crop(raw, row, col)
        frames = [radar.Frame(ts - timedelta(minutes=5), crop), radar.Frame(ts, crop)]
        radar.analyse(frames, now)
        took = time.perf_counter() - started
        need(len(crop) > 10000, "radar crop is too small")
        return f"frame {ts:%H:%M} UTC, {len(raw) // 1024} KB, decoded and analysed in {took * 1000:.0f} ms"
    raise AssertionError("no radar frame in the last 20 minutes")


async def check_open_meteo(session: aiohttp.ClientSession, cost: Cost) -> str:
    with metered(cost):
        data = await open_meteo.async_fetch_open_meteo(session, LAT, LON)
    need(len(data.times) >= 48, f"only {len(data.times)} hours")
    need(data.value("european_aqi", datetime.now(UTC)) is not None, "no air quality index for the current hour")
    return f"{len(data.times)} hours, {len(data.series)} series"


CHECKS: list[tuple[str, Callable[[aiohttp.ClientSession, Cost], Awaitable[str]]]] = [
    ("point and station lists", check_lists),
    ("forecast", check_forecast),
    ("station and rain gauge", check_station),
    ("pollen", check_pollen),
    ("warnings (MeteoAlarm)", check_warnings),
    ("radar", check_radar),
    ("air quality (Open-Meteo)", check_open_meteo),
]


async def main() -> int:
    failed = 0
    total = Cost()
    async with aiohttp.ClientSession() as session:
        for name, check in CHECKS:
            cost = Cost()
            try:
                try:
                    said = await check(session, cost)
                except aiohttp.ClientConnectionError:
                    # a lost connection or a DNS hiccup is not a changed source: once more
                    await asyncio.sleep(20)
                    said = await check(session, cost)
            except Exception as err:  # noqa: BLE001 - every kind of failure is a finding here
                failed += 1
                print(f"FAIL  {name}: {type(err).__name__}: {err}")
            else:
                print(f"ok    {name}: {said} [{cost.requests} requests, {cost.bytes / 1024:.0f} KB]")
            total(cost.requests, cost.bytes)
    print(f"{len(CHECKS) - failed} of {len(CHECKS)} sources as expected; {total.requests} requests, {total.bytes / 1e6:.1f} MB")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
