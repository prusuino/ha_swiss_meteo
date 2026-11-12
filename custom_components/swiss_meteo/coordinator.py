"""Data coordinators: the local forecast of one point, the 10-minute
values of one SwissMetNet station and, when one is chosen, the 10-minute
precipitation of a station of the precipitation network.

The forecast coordinator wakes every 15 minutes but reads only when a new
model run has appeared (one HEAD request tells). The daily values are
read at most every three hours — they change little from run to run — and
the hourly values with every new run; what a read cost is kept for the
diagnostics entities, so the traffic stays visible."""
from __future__ import annotations

from typing import TYPE_CHECKING

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EXTENDED,
    CONF_HOURLY,
    CONF_POINT_ID,
    CONF_POINT_TYPE,
    CONF_PRECIP_STATION,
    CONF_STATION,
    DAILY_PARAMS,
    DOMAIN,
    EXTENDED_PARAMS,
    HOURLY_PARAMS,
    STATION_INTERVAL_MINUTES,
)
from .issues import IssueReporter
from .ogd import (
    OgdError,
    OgdUnavailable,
    StationReading,
    async_catalogue_latest_run,
    async_fetch_forecast,
    async_fetch_precip_reading,
    async_fetch_station_reading,
    async_find_latest_run,
)

if TYPE_CHECKING:
    from .open_meteo import OpenMeteoCoordinator
    from .pollen import PollenCoordinator
    from .meteoalarm import WarningsCoordinator
    from .radar import RadarCoordinator

_LOGGER = logging.getLogger(__name__)

Series = list[tuple[datetime, float | None]]

_CHECK_INTERVAL = timedelta(minutes=15)
_DAILY_MAX_AGE = timedelta(hours=3)
_STATION_MAX_AGE = timedelta(minutes=45)


@dataclass
class ForecastSnapshot:
    """What the entities read: the newest values per parameter."""

    run: datetime | None = None
    daily: dict[str, Series] = field(default_factory=dict)
    hourly: dict[str, Series] = field(default_factory=dict)
    daily_fetched: datetime | None = None
    hourly_fetched: datetime | None = None
    missing: list[str] = field(default_factory=list)
    # traffic since local midnight
    traffic_day: datetime | None = None
    requests_today: int = 0
    bytes_today: int = 0
    last_requests: int = 0
    last_bytes: int = 0


# A kept run older than this is no forecast any more: the entities go unavailable.
_FORECAST_MAX_AGE = timedelta(hours=12)


class ForecastCoordinator(DataUpdateCoordinator[ForecastSnapshot]):
    """The local forecast of the entry's point."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} forecast", update_interval=_CHECK_INTERVAL, config_entry=entry)
        self._warned_run: datetime | None = None
        self.entry = entry
        self.point = (int(entry.data[CONF_POINT_ID]), int(entry.data[CONF_POINT_TYPE]))
        self.hourly_enabled = bool(entry.options.get(CONF_HOURLY, entry.data.get(CONF_HOURLY, True)))
        self.extended_enabled = bool(entry.options.get(CONF_EXTENDED, entry.data.get(CONF_EXTENDED, False)))
        self._snapshot = ForecastSnapshot()
        self.issues = IssueReporter(hass, entry.entry_id)

    async def _async_update_data(self) -> ForecastSnapshot:
        # A kept run is not a failure; only a refresh that leaves the entity
        # without a usable forecast counts towards the repair notice.
        try:
            snap = await self._async_fetch()
        except UpdateFailed as err:
            self.issues.failure("forecast_unreachable", {"error": str(err)})
            raise
        self.issues.clear("forecast_unreachable")
        return snap

    def _account(self, snap: ForecastSnapshot, requests: int, nbytes: int) -> None:
        today = dt_util.start_of_local_day()
        if snap.traffic_day != today:
            snap.traffic_day = today
            snap.requests_today = 0
            snap.bytes_today = 0
        snap.requests_today += requests
        snap.bytes_today += nbytes
        snap.last_requests = requests
        snap.last_bytes = nbytes

    @staticmethod
    def _usable(snap: ForecastSnapshot, now: datetime) -> bool:
        """Whether the kept run is still recent enough to show."""
        if snap.run is None:
            return False
        run = snap.run if snap.run.tzinfo else snap.run.replace(tzinfo=timezone.utc)
        return now - run <= _FORECAST_MAX_AGE

    async def _async_fetch(self) -> ForecastSnapshot:
        session = async_get_clientsession(self.hass)
        snap = self._snapshot
        now = dt_util.utcnow()
        try:
            run = await async_find_latest_run(session, now)
            if run is None:
                run = await async_catalogue_latest_run(session)
        except OgdUnavailable as err:
            if self._usable(snap, now):
                _LOGGER.debug("Run check failed, keeping run %s: %s", snap.run, err)
                return snap
            raise UpdateFailed(str(err)) from err
        # One probe per check; a HEAD costs no payload.
        self._account(snap, 1, 0)
        if run is None:
            if self._usable(snap, now):
                return snap
            raise UpdateFailed("MeteoSwiss has published no local forecast run for the last hours")

        new_run = run != snap.run
        need_daily = (
            new_run
            and (snap.daily_fetched is None or now - snap.daily_fetched >= _DAILY_MAX_AGE)
        ) or (snap.daily_fetched is not None and dt_util.as_local(snap.daily_fetched).date() != dt_util.now().date())
        need_hourly = self.hourly_enabled and (new_run or not snap.hourly)
        if not need_daily and not need_hourly:
            return snap

        missing: list[str] = []
        try:
            if need_daily:
                data = await async_fetch_forecast(session, run, self.point, DAILY_PARAMS)
                snap.daily = data.series
                snap.daily_fetched = now
                missing += data.missing
                self._account(snap, data.stats.requests, data.stats.bytes)
            if need_hourly:
                params = HOURLY_PARAMS + (EXTENDED_PARAMS if self.extended_enabled else ())
                data = await async_fetch_forecast(session, run, self.point, params)
                snap.hourly = data.series
                snap.hourly_fetched = now
                missing += data.missing
                self._account(snap, data.stats.requests, data.stats.bytes)
        except OgdUnavailable as err:
            if self._usable(snap, now):
                if self._warned_run != run:
                    self._warned_run = run
                    _LOGGER.warning("Forecast run %s not read, keeping the previous one: %s", run, err)
                else:
                    _LOGGER.debug("Forecast run %s still not read: %s", run, err)
                return snap
            raise UpdateFailed(str(err)) from err
        except OgdError as err:
            raise UpdateFailed(str(err)) from err
        snap.run = run
        snap.missing = missing
        if missing:
            _LOGGER.debug("Run %s: parameters not read: %s", run, ", ".join(missing))
        return snap


class StationCoordinator(DataUpdateCoordinator[StationReading]):
    """The newest 10-minute values of the entry's station."""

    _conf = CONF_STATION  # the entry key that names the station
    _issue = "station_unreadable"  # the Repairs notice after an hour of failures
    _what = "station"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN} {self._what}", update_interval=timedelta(minutes=STATION_INTERVAL_MINUTES), config_entry=entry
        )
        self.entry = entry
        self.station = str(entry.options.get(self._conf, entry.data.get(self._conf, "")))
        self.issues = IssueReporter(hass, entry.entry_id)

    async def _async_read(self) -> StationReading:
        return await async_fetch_station_reading(async_get_clientsession(self.hass), self.station)

    async def _async_update_data(self) -> StationReading:
        try:
            reading = await self._async_read()
        except OgdError as err:
            # An hour of failures (six 10-minute refreshes): the station file
            # is gone or the station was discontinued, say so under Repairs.
            self.issues.failure(self._issue, {"station": self.station, "error": str(err)}, after=6)
            raise UpdateFailed(str(err)) from err
        self.issues.clear(self._issue)
        return reading

    @property
    def fresh(self) -> bool:
        """False once the newest row is older than the publication gap
        a station outage would cause — the sensors go unavailable then."""
        return self.data is not None and dt_util.utcnow() - self.data.timestamp <= _STATION_MAX_AGE


class PrecipCoordinator(StationCoordinator):
    """The newest 10-minute precipitation of the entry's precipitation
    station: a rain gauge of the automatic precipitation network, read and
    judged like a weather station, with a file and a notice of its own."""

    _conf = CONF_PRECIP_STATION
    _issue = "precip_station_unreadable"
    _what = "precipitation station"

    async def _async_read(self) -> StationReading:
        return await async_fetch_precip_reading(async_get_clientsession(self.hass), self.station)


@dataclass
class EntryData:
    forecast: ForecastCoordinator
    station: StationCoordinator | None
    precip: PrecipCoordinator | None = None
    pollen: "PollenCoordinator | None" = None
    warnings: "WarningsCoordinator | None" = None
    radar: "RadarCoordinator | None" = None
    open_meteo: "OpenMeteoCoordinator | None" = None
