"""Import of the station's measurement history into Home Assistant's
long-term statistics.

MeteoSwiss publishes, next to the 10-minute "now" file of every
SwissMetNet station, its archive: hourly values in ten-year files since
1980 and daily values since the station's start. The `import_history`
action reads those files and writes them as statistics — the mean, the
minimum and the maximum of the station sensors (so a statistics graph of
the temperature sensor shows decades), and the daily or hourly totals of
precipitation, sunshine, evaporation and heating degree days as separate
statistics (`swiss_meteo:<id>_precipitation` …)."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    async_import_statistics,
    get_last_statistics,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import COLLECTION_STATIONS, DATA_BASE, DOMAIN, USER_AGENT

_LOGGER = logging.getLogger(__name__)

try:  # Home Assistant 2025.4+: mean_type replaces has_mean
    from homeassistant.components.recorder.models import StatisticMeanType
except ImportError:  # pragma: no cover
    StatisticMeanType = None  # type: ignore[assignment]
try:  # the unit class of a unit, required in the metadata from 2026.11
    from homeassistant.components.recorder.statistics import STATISTIC_UNIT_TO_UNIT_CONVERTER
except ImportError:  # pragma: no cover
    STATISTIC_UNIT_TO_UNIT_CONVERTER = {}  # type: ignore[assignment]


def _unit_class(unit: str | None) -> str | None:
    converter = STATISTIC_UNIT_TO_UNIT_CONVERTER.get(unit)
    return getattr(converter, "UNIT_CLASS", None) if converter is not None else None

# sensor key -> (group, hourly (mean, min, max), daily (mean, min, max))
MEASUREMENTS: dict[str, tuple[str, tuple[str, str | None, str | None], tuple[str, str | None, str | None]]] = {
    "temperature": ("temperature", ("tre200h0", "tre200hn", "tre200hx"), ("tre200d0", "tre200dn", "tre200dx")),
    "temperature_5cm": ("temperature", ("tre005h0", "tre005hn", None), ("tre005d0", "tre005dn", "tre005dx")),
    "dew_point": ("temperature", ("tde200h0", None, None), ("", None, None)),
    "humidity": ("humidity", ("ure200h0", None, None), ("ure200d0", None, None)),
    "vapour_pressure": ("humidity", ("pva200h0", None, None), ("pva200d0", None, None)),
    "pressure_qnh": ("pressure", ("pp0qnhh0", None, None), ("pp0qnhd0", None, None)),
    "pressure_qff": ("pressure", ("pp0qffh0", None, None), ("pp0qffd0", None, None)),
    "pressure_station": ("pressure", ("prestah0", None, None), ("prestad0", None, None)),
    "geopotential_850": ("pressure", ("ppz850h0", None, None), ("ppz850d0", None, None)),
    "geopotential_700": ("pressure", ("ppz700h0", None, None), ("ppz700d0", None, None)),
    "wind_speed": ("wind", ("fu3010h0", None, None), ("fu3010d0", None, None)),
    "wind_gust": ("wind", ("fu3010h1", None, "fu3010h1"), ("fu3010d1", None, "fu3010d1")),
    "wind_gust_3s": ("wind", ("fu3010h3", None, "fu3010h3"), ("fu3010d3", None, "fu3010d3")),
    "wind_direction": ("wind", ("dkl010h0", None, None), ("dkl010d0", None, None)),
    "foehn_index": ("wind", ("wcc006h0", None, None), ("wcc006d0", None, None)),
    "global_radiation": ("radiation", ("gre000h0", None, None), ("gre000d0", None, None)),
    "diffuse_radiation": ("radiation", ("ods000h0", None, None), ("ods000d0", None, None)),
    "longwave_incoming": ("radiation", ("oli000h0", None, None), ("oli000d0", None, None)),
    "longwave_outgoing": ("radiation", ("olo000h0", None, None), ("olo000d0", None, None)),
    "reflected_radiation": ("radiation", ("osr000h0", None, None), ("osr000d0", None, None)),
    "snow_depth": ("snow", ("htoauths", None, None), ("htoautd0", None, None)),
    "soil_temperature_5cm": ("soil", ("tso005hs", None, None), ("tso005d0", None, None)),
    "soil_temperature_10cm": ("soil", ("tso010hs", None, None), ("tso010d0", None, None)),
    "soil_temperature_20cm": ("soil", ("tso020hs", None, None), ("tso020d0", None, None)),
}
# totals: statistic suffix -> (group, hourly column, daily column, unit, name)
TOTALS: dict[str, tuple[str, str, str, str, str]] = {
    "precipitation": ("precipitation", "rre150h0", "rka150d0", "mm", "Precipitation"),
    "sunshine": ("sunshine", "sre000h0", "sre000d0", "min", "Sunshine duration"),
    "evaporation": ("evaporation", "erefaoh0", "erefaod0", "mm", "Reference evaporation (FAO)"),
    "heating_degree_days": ("heating_degree_days", "", "xno000d0", "K·d", "Heating degree days (12/20)"),
}
GROUPS = ("temperature", "humidity", "pressure", "wind", "radiation", "snow", "soil", "precipitation", "sunshine", "evaporation", "heating_degree_days")

_TS_FORMAT = "%d.%m.%Y %H:%M"


class HistoryError(Exception):
    """The archive could not be read."""


def _files(station: str, resolution: str, years: int, now: datetime) -> list[str]:
    """The archive files that cover the last `years` years."""
    a = station.lower()
    base = f"{DATA_BASE}/{COLLECTION_STATIONS}/{a}/ogd-smn_{a}"
    if resolution == "daily":
        out = [f"{base}_d_recent.csv"]
        if years > 1:
            out.append(f"{base}_d_historical.csv")
        return out
    out = [f"{base}_h_recent.csv"]
    first_year = now.year - years + 1
    for decade in range((first_year // 10) * 10, now.year, 10):
        if decade + 9 < now.year or decade <= now.year - 1:
            out.append(f"{base}_h_historical_{decade}-{decade + 9}.csv")
    return sorted(set(out))


async def _fetch(session: aiohttp.ClientSession, url: str) -> tuple[bytes, int]:
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status == 404:
                return b"", 1
            if resp.status != 200:
                raise HistoryError(f"{url}: HTTP {resp.status}")
            return await resp.read(), 1
    except aiohttp.ClientError as err:
        raise HistoryError(f"{url}: {err}") from err


def _parse(raw: bytes, since: datetime, shift_hours: int) -> list[dict[str, Any]]:
    """Rows newer than `since` as dicts of floats, keyed by column, with the
    row's start time under "start" (hourly values are stamped at the end
    of their hour; daily values at the day's start)."""
    text = raw.decode("latin-1")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = next(reader, None)
    if not header:
        return []
    out: list[dict[str, Any]] = []
    for row in reader:
        if len(row) < 2:
            continue
        try:
            ts = datetime.strptime(row[1], _TS_FORMAT).replace(tzinfo=timezone.utc) - timedelta(hours=shift_hours)
        except ValueError:
            continue
        if ts < since:
            continue
        rec: dict[str, Any] = {"start": ts}
        for name, value in zip(header[2:], row[2:]):
            if value not in ("", "-"):
                try:
                    rec[name] = float(value)
                except ValueError:
                    pass
        out.append(rec)
    return out


def _meta(statistic_id: str, source: str, name: str, unit: str | None, has_mean: bool, has_sum: bool) -> StatisticMetaData:
    meta: dict[str, Any] = {
        "statistic_id": statistic_id,
        "source": source,
        "name": name,
        "unit_of_measurement": unit,
        "unit_class": _unit_class(unit),
        "has_sum": has_sum,
    }
    if StatisticMeanType is not None:
        meta["mean_type"] = StatisticMeanType.ARITHMETIC if has_mean else StatisticMeanType.NONE
    else:  # pragma: no cover
        meta["has_mean"] = has_mean
    return meta  # type: ignore[return-value]


async def async_import_history(
    hass: HomeAssistant,
    *,
    station: str,
    entity_prefix: str,
    statistic_prefix: str,
    units: dict[str, str | None],
    years: int,
    resolution: str,
    groups: set[str],
    account=None,
) -> dict[str, Any]:
    """Read the archive and write the statistics. `units` maps sensor key
    to the unit of the entity (only keys present get entity statistics).
    Returns a summary per statistic."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    now = dt_util.utcnow()
    since = now.replace(year=now.year - years + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    shift = 1 if resolution == "hourly" else 0
    rows: list[dict[str, Any]] = []
    requests = 0
    nbytes = 0
    for url in _files(station, resolution, years, now):
        raw, n = await _fetch(session, url)
        requests += n
        nbytes += len(raw)
        if raw:
            rows += await hass.async_add_executor_job(_parse, raw, since, shift)
    if account is not None:
        account(requests, nbytes)
    if not rows:
        raise HistoryError(f"No archive rows for station {station}")
    rows.sort(key=lambda r: r["start"])
    # the files overlap at the year boundary: keep one row per start
    dedup: dict[datetime, dict[str, Any]] = {}
    for r in rows:
        dedup.setdefault(r["start"], r).update(r)
    rows = list(dedup.values())
    col = 1 if resolution == "hourly" else 2
    summary: dict[str, Any] = {"station": station, "resolution": resolution, "rows": len(rows), "first": rows[0]["start"].isoformat(), "last": rows[-1]["start"].isoformat(), "statistics": {}}

    for key, (group, hourly, daily) in MEASUREMENTS.items():
        if group not in groups or key not in units:
            continue
        mean_c, min_c, max_c = (hourly, daily)[col - 1]
        if not mean_c:
            continue
        stats: list[StatisticData] = []
        for r in rows:
            if mean_c not in r:
                continue
            item: dict[str, Any] = {"start": r["start"], "mean": r[mean_c]}
            item["min"] = r.get(min_c, r[mean_c]) if min_c else r[mean_c]
            item["max"] = r.get(max_c, r[mean_c]) if max_c else r[mean_c]
            stats.append(item)  # type: ignore[arg-type]
        if not stats:
            continue
        entity_id = f"sensor.{entity_prefix}_{key}"
        async_import_statistics(hass, _meta(entity_id, "recorder", key, units[key], True, False), stats)
        summary["statistics"][entity_id] = len(stats)

    for suffix, (group, hourly_c, daily_c, unit, name) in TOTALS.items():
        if group not in groups:
            continue
        column = hourly_c if resolution == "hourly" else daily_c
        if not column:
            continue
        statistic_id = f"{DOMAIN}:{statistic_prefix}_{suffix}"
        first_start = rows[0]["start"]
        base = 0.0
        last = await get_instance(hass).async_add_executor_job(get_last_statistics, hass, 1, statistic_id, True, {"sum"})
        if last and last.get(statistic_id):
            prev = last[statistic_id][0]
            prev_start = prev.get("start")
            if isinstance(prev_start, (int, float)):
                prev_start = datetime.fromtimestamp(prev_start, tz=timezone.utc)
            if prev_start is not None and prev_start < first_start and prev.get("sum") is not None:
                base = float(prev["sum"])
        running = base
        stats = []
        for r in rows:
            if column not in r:
                continue
            running += r[column]
            stats.append({"start": r["start"], "state": r[column], "sum": round(running, 3)})  # type: ignore[arg-type]
        if not stats:
            continue
        async_add_external_statistics(hass, _meta(statistic_id, DOMAIN, f"{station} {name}", unit, False, True), stats)
        summary["statistics"][statistic_id] = len(stats)
    _LOGGER.info("Station %s: %s rows (%s) imported into %d statistics, %.1f MB read", station, len(rows), resolution, len(summary["statistics"]), nbytes / 1e6)
    return summary
