"""The station's climate: what is normal for the day, the day's records,
yesterday against the normal, and the first frost and snow of the season.

Two files of the station are read whole:

* The daily archive since the station started (`…_d_historical.csv`, 6 MB
  plain and about 1.7 MB compressed for a station that began in 1864). It
  changes once a year, so it is read once, reduced to a small table per
  calendar day and kept in `.storage`. Every 30 days (daily in the new
  year until last year is in it) a HEAD request looks whether MeteoSwiss
  has replaced it.
* The daily values of the current year (`…_d_recent.csv`, about 50 KB),
  read every three hours: yesterday's row appears there in the morning.

The normal is the mean over the reference period 1991–2020 of all days
within a week of the calendar day (15 days by 30 years), the usual way to
get a smooth daily normal from daily values. A station that covers fewer
than ten years of the period has no normal. Records are the highest
maximum and the lowest minimum ever measured on the calendar day,
including the current year.

For the climate stripes the table also holds the mean temperature of
every year the station measured on at least 350 days, and for the month
so far the normal precipitation of each month (the mean monthly total
over the reference period).
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import COLLECTION_STATIONS, CONF_STATION, DATA_BASE, DOMAIN, USER_AGENT
from .ogd import OgdError, OgdUnavailable, _fetch, _float
from .traffic import Account, metered

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(hours=3)
NORMAL_PERIOD = (1991, 2020)
NORMAL_WINDOW_DAYS = 7  # days to either side of the calendar day
NORMAL_MIN_YEARS = 10
FROST_BELOW = 0.0  # a frost day: the minimum is below 0 °C
SNOW_FROM_CM = 1.0
SEASON_START_MONTH = 7  # the cold season is counted from 1 July
STORAGE_VERSION = 1
YEAR_MIN_DAYS = 350  # days with a mean for a year to count
STRIPES_REFERENCE = (1961, 1990)  # the stripes' zero, when the station covers it
STRIPES_REFERENCE_MIN_YEARS = 20
_ARCHIVE_CHECK = timedelta(days=30)
# In the new year the archive still ends in December of the year before the
# last: it is looked at daily until MeteoSwiss has added last year.
_ARCHIVE_CHECK_BEHIND = timedelta(days=1)
_YESTERDAY_MAX_DAYS = 2  # yesterday's row appears in the morning; an older one is not "yesterday"
_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=10)

MEAN, HIGH, LOW, RAIN, SUN, SNOW = "tre200d0", "tre200dx", "tre200dn", "rka150d0", "sre000d0", "htoautd0"
_COLUMNS = (MEAN, HIGH, LOW, RAIN, SUN, SNOW)

Days = dict[date, dict[str, float | None]]


def archive_url(station: str) -> str:
    a = station.lower()
    return f"{DATA_BASE}/{COLLECTION_STATIONS}/{a}/ogd-smn_{a}_d_historical.csv"


def recent_url(station: str) -> str:
    a = station.lower()
    return f"{DATA_BASE}/{COLLECTION_STATIONS}/{a}/ogd-smn_{a}_d_recent.csv"


def climate_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.climate_{entry_id}")


def parse_days(body: bytes) -> Days:
    """The daily rows of a station file, by date. Read row by row and only
    the needed columns: as a list of mappings the archive of an old station
    (59 000 rows of 41 columns) would take more than 100 MB of memory."""
    days: Days = {}
    reader = csv.reader(io.TextIOWrapper(io.BytesIO(body), encoding="latin-1", newline=""), delimiter=";")
    header = next(reader, [])
    if "reference_timestamp" not in header:
        return days
    stamp = header.index("reference_timestamp")
    columns = {column: header.index(column) if column in header else None for column in _COLUMNS}
    for row in reader:
        try:
            text = row[stamp].strip()
            day = date(int(text[6:10]), int(text[3:5]), int(text[0:2]))
        except (IndexError, ValueError):
            continue
        days[day] = {column: _float(row[i]) if i is not None and i < len(row) else None for column, i in columns.items()}
    return days


def _same_day(year: int, month: int, day: int) -> date:
    """The calendar day in a year; 29 February falls on the 28th elsewhere."""
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, 2, 28)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def season_first(days: Days, season: int, column: str, hit) -> date | None:
    """The first day from 1 July of `season` to 30 June after it on which
    `hit(value)` holds."""
    start, end = date(season, SEASON_START_MONTH, 1), date(season + 1, SEASON_START_MONTH, 1)
    found = [day for day, row in days.items() if start <= day < end and row.get(column) is not None and hit(row[column])]
    return min(found) if found else None


def build_table(days: Days) -> dict[str, Any]:
    """The archive reduced to what the sensors need: per calendar day the
    normal (mean, high, low, the years behind it) and the records with
    their years, and the first frost and snow of the archive's last season."""
    table: dict[str, list] = {}
    first, last = NORMAL_PERIOD
    by_day: dict[tuple[int, int], list[tuple[date, dict[str, float | None]]]] = {}
    for when, row in days.items():
        by_day.setdefault((when.month, when.day), []).append((when, row))
    for month, day in ((d.month, d.day) for d in (date(2000, 1, 1) + timedelta(days=n) for n in range(366))):
        sums: dict[str, list[float]] = {MEAN: [], HIGH: [], LOW: []}
        years = 0
        for year in range(first, last + 1):
            centre = _same_day(year, month, day)
            seen = False
            for offset in range(-NORMAL_WINDOW_DAYS, NORMAL_WINDOW_DAYS + 1):
                row = days.get(centre + timedelta(days=offset))
                if row is None:
                    continue
                for column, values in sums.items():
                    if row[column] is not None:
                        values.append(row[column])
                        seen = seen or column == MEAN
            years += seen
        normal = [_mean(sums[MEAN]), _mean(sums[HIGH]), _mean(sums[LOW])] if years >= NORMAL_MIN_YEARS else [None, None, None]
        highest: tuple[float, int] | None = None
        lowest: tuple[float, int] | None = None
        for when, row in by_day.get((month, day), ()):
            if row[HIGH] is not None and (highest is None or row[HIGH] > highest[0]):
                highest = (row[HIGH], when.year)
            if row[LOW] is not None and (lowest is None or row[LOW] < lowest[0]):
                lowest = (row[LOW], when.year)
        table[f"{month:02d}-{day:02d}"] = [*normal, years, *(highest or (None, None)), *(lowest or (None, None))]
    # the mean of every complete year, for the stripes
    per_year: dict[int, list[float]] = {}
    rain: dict[tuple[int, int], list[float]] = {}
    for when, row in days.items():
        if row[MEAN] is not None:
            per_year.setdefault(when.year, []).append(row[MEAN])
        if row[RAIN] is not None and first <= when.year <= last:
            rain.setdefault((when.year, when.month), []).append(row[RAIN])
    yearly = {str(year): round(sum(values) / len(values), 2) for year, values in sorted(per_year.items()) if len(values) >= YEAR_MIN_DAYS}
    # the normal monthly precipitation: months measured on at least 27 days
    monthly: dict[str, list] = {}
    for month in range(1, 13):
        totals = [sum(values) for (_year, m), values in rain.items() if m == month and len(values) >= 27]
        monthly[f"{month:02d}"] = [round(sum(totals) / len(totals), 1) if len(totals) >= NORMAL_MIN_YEARS else None, len(totals)]
    through = max(days) if days else None
    season = through.year if through and through.month >= SEASON_START_MONTH else (through.year - 1 if through else None)
    frost = season_first(days, season, LOW, lambda v: v < FROST_BELOW) if season else None
    snow = season_first(days, season, SNOW, lambda v: v >= SNOW_FROM_CM) if season else None
    return {
        "days": table,
        "years": yearly,
        "months": monthly,
        "through": through.isoformat() if through else None,
        "first_year": min(days).year if days else None,
        "season": season,
        "frost": frost.isoformat() if frost else None,
        "snow": snow.isoformat() if snow else None,
    }


@dataclass
class Climate:
    """What the sensors show."""

    day: date  # the calendar day the normal and the records are for (today)
    normal_mean: float | None
    normal_high: float | None
    normal_low: float | None
    normal_years: int
    record_high: float | None
    record_high_year: int | None
    record_low: float | None
    record_low_year: int | None
    first_year: int | None  # the station's first year in the archive
    yesterday: date | None  # the newest day with values
    yesterday_values: dict[str, float | None]
    anomaly: float | None  # that day's mean against its normal
    first_frost: date | None
    first_snow: date | None
    fetched: datetime
    # the running month up to the newest measured day
    month_days: int = 0
    month_mean: float | None = None
    month_normal: float | None = None  # the normal of the same days
    month_precipitation: float | None = None
    month_precipitation_normal: float | None = None  # of the whole month


def assemble(table: dict[str, Any], recent: Days, today: date, now: datetime) -> Climate:
    """Today's figures from the stored table and the current year's days."""
    key = f"{today.month:02d}-{today.day:02d}"
    mean, high, low, years, rec_high, rec_high_year, rec_low, rec_low_year = table["days"].get(key) or [None] * 8
    # this year's days can set a record too
    for when, row in recent.items():
        if (when.month, when.day) != (today.month, today.day):
            continue
        if row[HIGH] is not None and (rec_high is None or row[HIGH] > rec_high):
            rec_high, rec_high_year = row[HIGH], when.year
        if row[LOW] is not None and (rec_low is None or row[LOW] < rec_low):
            rec_low, rec_low_year = row[LOW], when.year
    measured = [day for day, row in recent.items() if row[MEAN] is not None and day < today]
    yesterday = max(measured) if measured else None
    if yesterday is not None and (today - yesterday).days > _YESTERDAY_MAX_DAYS:
        yesterday = None  # the station has stopped reporting
    values = recent[yesterday] if yesterday else {}
    anomaly = None
    if yesterday is not None:
        its_normal = (table["days"].get(f"{yesterday.month:02d}-{yesterday.day:02d}") or [None])[0]
        if its_normal is not None:
            anomaly = round(values[MEAN] - its_normal, 1)
    season = today.year if today.month >= SEASON_START_MONTH else today.year - 1
    frost = season_first(recent, season, LOW, lambda v: v < FROST_BELOW)
    snow = season_first(recent, season, SNOW, lambda v: v >= SNOW_FROM_CM)
    # the season may have begun in the archive's last year, or in days that were
    # in the current file before the new year and are in neither file now
    for known in (table, table.get("found") or {}):
        if known.get("season") == season:
            frost = min(filter(None, (frost, date.fromisoformat(known["frost"]) if known.get("frost") else None)), default=None)
            snow = min(filter(None, (snow, date.fromisoformat(known["snow"]) if known.get("snow") else None)), default=None)
    # the running month: the days measured so far against the normals of the same days
    so_far = sorted(day for day in measured if (day.year, day.month) == (today.year, today.month))
    month_mean = _mean([recent[day][MEAN] for day in so_far])
    normals = [(table["days"].get(f"{day.month:02d}-{day.day:02d}") or [None])[0] for day in so_far]
    month_normal = _mean([v for v in normals if v is not None]) if so_far and all(v is not None for v in normals) else None
    wet = [recent[day][RAIN] for day in so_far if recent[day][RAIN] is not None]
    return Climate(
        day=today,
        month_days=len(so_far),
        month_mean=month_mean,
        month_normal=month_normal,
        month_precipitation=round(sum(wet), 1) if wet else None,
        month_precipitation_normal=((table.get("months") or {}).get(f"{today.month:02d}") or [None])[0],
        normal_mean=mean,
        normal_high=high,
        normal_low=low,
        normal_years=years or 0,
        record_high=rec_high,
        record_high_year=rec_high_year,
        record_low=rec_low,
        record_low_year=rec_low_year,
        first_year=table.get("first_year"),
        yesterday=yesterday,
        yesterday_values=dict(values),
        anomaly=anomaly,
        first_frost=frost,
        first_snow=snow,
        fetched=now,
    )


class ClimateCoordinator(DataUpdateCoordinator[Climate]):
    """The climate figures of the entry's station."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, account: Account | None = None) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} climate", update_interval=UPDATE_INTERVAL, config_entry=entry)
        self.entry = entry
        self.station = str(entry.options.get(CONF_STATION, entry.data.get(CONF_STATION, "")))
        self._account = account
        self._store = climate_store(hass, entry.entry_id)
        self._table: dict[str, Any] | None = None
        self._loaded = False
        self._warned = False

    def stripes(self) -> dict[str, Any] | None:
        """The yearly means for the climate stripes card, with the mean they
        are coloured against: that of 1961-1990 when the station covers at
        least twenty of those years, else that of all its years."""
        if self._table is None or not self._table.get("years"):
            return None
        years = {int(year): value for year, value in self._table["years"].items()}
        inside = [value for year, value in years.items() if STRIPES_REFERENCE[0] <= year <= STRIPES_REFERENCE[1]]
        whole = len(inside) < STRIPES_REFERENCE_MIN_YEARS
        basis = list(years.values()) if whole else inside
        return {
            "years": [{"year": year, "mean": value} for year, value in sorted(years.items())],
            "reference": round(sum(basis) / len(basis), 2),
            "reference_period": [min(years), max(years)] if whole else list(STRIPES_REFERENCE),
        }

    async def _archive_stamp(self, session: aiohttp.ClientSession) -> str | None:
        """When MeteoSwiss last wrote the archive, without reading it."""
        try:
            async with session.head(archive_url(self.station), headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT) as resp:
                if self._account is not None:
                    self._account(1, 0)
                return resp.headers.get("Last-Modified") if resp.status == 200 else None
        except (TimeoutError, aiohttp.ClientError):
            return None

    async def _async_table(self, session: aiohttp.ClientSession, now: datetime) -> dict[str, Any]:
        if not self._loaded:
            self._loaded = True
            stored = await self._store.async_load()
            # a table without the yearly means is not one of this version: it is built anew
            if isinstance(stored, dict) and stored.get("station") == self.station and isinstance(stored.get("days"), dict) and isinstance(stored.get("years"), dict):
                self._table = stored
        table = self._table
        stamp: str | None = None
        if table is not None:
            checked = dt_util.parse_datetime(table.get("checked") or "")
            behind = (table.get("through") or "")[:4] < str(dt_util.now().year - 1)
            if checked is not None and now - checked < (_ARCHIVE_CHECK_BEHIND if behind else _ARCHIVE_CHECK):
                return table
            stamp = await self._archive_stamp(session)
            if stamp is None or stamp == table.get("stamp"):
                # unchanged, or not reachable now: keep the table, look again in a month or at the next refresh
                if stamp is not None:
                    table["checked"] = now.isoformat()
                    self._store.async_delay_save(lambda: table, 60)
                return table
        else:
            stamp = await self._archive_stamp(session)
        try:
            days = await self.hass.async_add_executor_job(parse_days, await _fetch(session, archive_url(self.station)))
            if not days:
                raise OgdError(f"the daily archive of {self.station} has no rows")
        except OgdError as err:
            if table is None:
                raise
            _LOGGER.debug("Renewed archive of %s not read, keeping the table: %s", self.station, err)
            return table
        fresh = await self.hass.async_add_executor_job(build_table, days)
        fresh.update(station=self.station, stamp=stamp, checked=now.isoformat())
        if table is not None and table.get("found"):
            fresh["found"] = table["found"]
        self._table = fresh
        self._store.async_delay_save(lambda: fresh, 60)
        return fresh

    async def _async_update_data(self) -> Climate:
        now = dt_util.utcnow()
        session = async_get_clientsession(self.hass)
        try:
            with metered(self._account):
                table = await self._async_table(session, now)
                recent = await self.hass.async_add_executor_job(parse_days, await _fetch(session, recent_url(self.station)))
        except OgdError as err:
            if self.data is not None and isinstance(err, OgdUnavailable) and now - self.data.fetched <= timedelta(days=2):
                if not self._warned:
                    self._warned = True
                    _LOGGER.warning("Climate files of %s not read, keeping the last figures: %s", self.station, err)
                return self.data
            raise UpdateFailed(str(err), translation_domain=DOMAIN, translation_key="read_failed", translation_placeholders={"error": str(err)}) from err
        self._warned = False
        climate = assemble(table, recent, dt_util.now().date(), now)
        self._remember(table, climate)
        return climate

    def _remember(self, table: dict[str, Any], climate: Climate) -> None:
        """Keep the season's first days: the current year's file starts anew
        in January, weeks before the archive gains the autumn."""
        found = {
            "season": climate.day.year if climate.day.month >= SEASON_START_MONTH else climate.day.year - 1,
            "frost": climate.first_frost.isoformat() if climate.first_frost else None,
            "snow": climate.first_snow.isoformat() if climate.first_snow else None,
        }
        if found != table.get("found"):
            table["found"] = found
            self._store.async_delay_save(lambda: table, 60)
