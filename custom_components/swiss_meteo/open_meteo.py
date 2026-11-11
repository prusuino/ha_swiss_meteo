"""Optional air quality, UV index and pollen forecast from Open-Meteo.

MeteoSwiss publishes none of the three as open data for a point, so this
part is opt-in and clearly separate: the values are *modelled* (Copernicus
CAMS European air quality forecast, a grid of about 11 km, hourly, four
days ahead), read from the free Open-Meteo air quality API. They are not
measurements and not official MeteoSwiss data.

One request an hour returns everything: the hourly series of four days
from local midnight. The current values are the ones of the running hour,
the daily maxima are taken from the same series.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_POINT_LAT, CONF_POINT_LON, DOMAIN, USER_AGENT
from .issues import IssueReporter

_LOGGER = logging.getLogger(__name__)

API_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
UPDATE_INTERVAL = timedelta(hours=1)
FORECAST_DAYS = 4
_TIMEOUT = aiohttp.ClientTimeout(total=30)
_HOUR = timedelta(hours=1)
# A forecast read some hours ago still covers the running hour: keep it over
# an outage this long before the sensors go unavailable.
_MAX_AGE = timedelta(hours=12)
# Failed hourly reads in a row before a repair notice is raised.
_ISSUE_AFTER = 6

AIR_QUALITY_PARAMS: tuple[str, ...] = ("european_aqi", "pm10", "pm2_5", "nitrogen_dioxide", "ozone")
UV_PARAMS: tuple[str, ...] = ("uv_index", "uv_index_clear_sky")
POLLEN_SPECIES: tuple[str, ...] = ("alder", "birch", "grass", "mugwort", "olive", "ragweed")
HOURLY_PARAMS: tuple[str, ...] = AIR_QUALITY_PARAMS + UV_PARAMS + tuple(f"{species}_pollen" for species in POLLEN_SPECIES)

# European Air Quality Index bands (upper bound, level).
AQI_LEVELS: tuple[str, ...] = ("good", "fair", "moderate", "poor", "very_poor", "extremely_poor")
_AQI_BOUNDS: tuple[float, ...] = (20, 40, 60, 80, 100)


class OpenMeteoError(Exception):
    """Open-Meteo could not be read or answered with something unusable."""


def aqi_level(value: float | None) -> str | None:
    """The European Air Quality Index band of an index value."""
    if value is None:
        return None
    for bound, level in zip(_AQI_BOUNDS, AQI_LEVELS):
        if value <= bound:
            return level
    return AQI_LEVELS[-1]


@dataclass(frozen=True)
class OpenMeteoData:
    """The hourly series of one read."""

    fetched: datetime
    times: tuple[datetime, ...]
    series: dict[str, tuple[float | None, ...]]

    def index_at(self, now: datetime) -> int | None:
        """The index of the hour `now` falls into, None outside the series."""
        if not self.times or now < self.times[0] or now >= self.times[-1] + _HOUR:
            return None
        return min(int((now - self.times[0]) / _HOUR), len(self.times) - 1)

    def value(self, key: str, now: datetime) -> float | None:
        """The value of the running hour."""
        index = self.index_at(now)
        values = self.series.get(key)
        if index is None or values is None:
            return None
        return values[index]

    def day_peak(self, key: str, day: date) -> tuple[float, datetime] | None:
        """The highest value of a local day and the hour it is reached."""
        best: tuple[float, datetime] | None = None
        for when, value in zip(self.times, self.series.get(key, ())):
            if value is None or dt_util.as_local(when).date() != day:
                continue
            if best is None or value > best[0]:
                best = (value, when)
        return best

    def day_max(self, key: str, day: date) -> float | None:
        peak = self.day_peak(key, day)
        return peak[0] if peak else None

    def daily_max(self, key: str) -> dict[str, float]:
        """The highest value of each local day in the series, by ISO date."""
        result: dict[str, float] = {}
        for when, value in zip(self.times, self.series.get(key, ())):
            if value is None:
                continue
            day = dt_util.as_local(when).date().isoformat()
            if day not in result or value > result[day]:
                result[day] = value
        return result


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_open_meteo(payload: Any, fetched: datetime) -> OpenMeteoData:
    """Turn the API answer into the hourly series."""
    if not isinstance(payload, dict):
        raise OpenMeteoError("answer is not a JSON object")
    if payload.get("error"):
        raise OpenMeteoError(str(payload.get("reason") or "error reported"))
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise OpenMeteoError("answer has no hourly values")
    stamps = hourly.get("time")
    if not isinstance(stamps, list) or not stamps:
        raise OpenMeteoError("answer has no time axis")
    try:
        times = tuple(dt_util.utc_from_timestamp(int(stamp)) for stamp in stamps)
    except (TypeError, ValueError, OverflowError, OSError) as err:
        raise OpenMeteoError("time axis is not readable") from err
    series: dict[str, tuple[float | None, ...]] = {}
    for key in HOURLY_PARAMS:
        values = hourly.get(key)
        if isinstance(values, list) and len(values) == len(times):
            series[key] = tuple(_number(value) for value in values)
    if not series:
        raise OpenMeteoError("answer has none of the requested values")
    return OpenMeteoData(fetched=fetched, times=times, series=series)


def request_params(lat: float, lon: float) -> dict[str, str]:
    """The query of the one request. The coordinates go out rounded to two
    decimals (about a kilometre), far finer than the model grid."""
    return {
        "latitude": f"{lat:.2f}",
        "longitude": f"{lon:.2f}",
        "hourly": ",".join(HOURLY_PARAMS),
        "forecast_days": str(FORECAST_DAYS),
        "timeformat": "unixtime",
        "timezone": "Europe/Zurich",
    }


async def async_fetch_open_meteo(session: aiohttp.ClientSession, lat: float, lon: float) -> OpenMeteoData:
    """Read the four-day hourly series for a place."""
    try:
        async with session.get(
            API_URL,
            params=request_params(lat, lon),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=_TIMEOUT,
        ) as resp:
            if resp.status != 200:
                raise OpenMeteoError(f"Open-Meteo answered {resp.status}")
            payload = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise OpenMeteoError(str(err) or type(err).__name__) from err
    return parse_open_meteo(payload, dt_util.utcnow())


class OpenMeteoCoordinator(DataUpdateCoordinator[OpenMeteoData]):
    """Air quality, UV index and pollen forecast for the entry's point."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} open-meteo", update_interval=UPDATE_INTERVAL, config_entry=entry)
        self.entry = entry
        self.lat = float(entry.data[CONF_POINT_LAT])
        self.lon = float(entry.data[CONF_POINT_LON])
        self.issues = IssueReporter(hass, entry.entry_id)
        self._warned = False

    async def _async_update_data(self) -> OpenMeteoData:
        try:
            data = await async_fetch_open_meteo(async_get_clientsession(self.hass), self.lat, self.lon)
        except OpenMeteoError as err:
            self.issues.failure("open_meteo_unreachable", {"error": str(err)}, after=_ISSUE_AFTER)
            if self.data is not None and dt_util.utcnow() - self.data.fetched <= _MAX_AGE:
                # The series read earlier still covers the coming hours.
                if not self._warned:
                    self._warned = True
                    _LOGGER.warning("Open-Meteo not read, keeping the last forecast: %s", err)
                return self.data
            raise UpdateFailed(str(err)) from err
        if self._warned:
            self._warned = False
            _LOGGER.info("Open-Meteo is readable again")
        self.issues.clear("open_meteo_unreachable")
        return data

    @property
    def fresh(self) -> bool:
        """False once the series no longer covers the running hour."""
        return self.data is not None and self.data.index_at(dt_util.utcnow()) is not None
