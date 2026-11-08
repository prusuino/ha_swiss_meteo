"""Pollen: the hourly concentrations of the seven allergenic species the
MeteoSwiss automatic pollen stations measure (open data), and the
MeteoSwiss load classes.

The station's file holds the current day's hours; the newest hour with a
value is the current concentration, the mean of the day's hours so far
is what the load classes are defined for ("mean daily concentration")."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .issues import IssueReporter

from .const import COLLECTION_POLLEN, CONF_POLLEN_STATION, DATA_BASE, DOMAIN
from .ogd import OgdError, _fetch, _float, _parse_csv, _parse_station_timestamp

_LOGGER = logging.getLogger(__name__)

POLLEN_STATIONS_META_URL = f"{DATA_BASE}/{COLLECTION_POLLEN}/ogd-pollen_meta_stations.csv"

# file column -> species key
POLLEN_PARAMS: dict[str, str] = {
    "kabetuh0": "birch",
    "khpoach0": "grasses",
    "kaalnuh0": "alder",
    "kacoryh0": "hazel",
    "kafaguh0": "beech",
    "kafraxh0": "ash",
    "kaquerh0": "oak",
}
SPECIES = tuple(POLLEN_PARAMS.values())

# MeteoSwiss load classes ("Belastungsklassen allergener Pollenarten",
# 2024): the upper bounds of low, moderate and high, in pollen/m³ of the
# mean daily concentration; above the last bound the load is very high.
LOAD_CLASSES: dict[str, tuple[int, int, int]] = {
    "hazel": (10, 69, 249),
    "alder": (10, 69, 249),
    "ash": (10, 99, 349),
    "birch": (10, 69, 299),
    "oak": (49, 129, 399),
    "beech": (49, 129, 399),
    "grasses": (19, 49, 149),
}
LEVELS = ("none", "low", "moderate", "high", "very_high")

UPDATE_INTERVAL = timedelta(minutes=30)
_MAX_AGE = timedelta(hours=4)


def level_for(species: str, value: float | None) -> str | None:
    """The load class of a concentration."""
    if value is None:
        return None
    bounds = LOAD_CLASSES.get(species)
    if bounds is None or value < 1:
        return "none"
    for level, bound in zip(("low", "moderate", "high"), bounds):
        if value <= bound:
            return level
    return "very_high"


@dataclass
class PollenStation:
    abbr: str
    name: str
    canton: str
    height: float | None
    lat: float
    lon: float


@dataclass
class PollenReading:
    abbr: str
    timestamp: datetime  # end of the newest hour with a value
    current: dict[str, float | None] = field(default_factory=dict)  # species -> newest hourly value
    daily_mean: dict[str, float | None] = field(default_factory=dict)  # species -> mean of the day so far
    hours: int = 0


async def async_fetch_pollen_stations(session: aiohttp.ClientSession) -> list[PollenStation]:
    rows = _parse_csv(await _fetch(session, POLLEN_STATIONS_META_URL))
    out: list[PollenStation] = []
    for row in rows:
        try:
            out.append(
                PollenStation(
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
    return out


def pollen_now_url(abbr: str) -> str:
    a = abbr.lower()
    return f"{DATA_BASE}/{COLLECTION_POLLEN}/{a}/ogd-pollen_{a}_h_now.csv"


async def async_fetch_pollen_reading(session: aiohttp.ClientSession, abbr: str) -> PollenReading:
    rows = _parse_csv(await _fetch(session, pollen_now_url(abbr)))
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    current: dict[str, float | None] = {}
    newest: datetime | None = None
    for row in rows:
        try:
            ts = _parse_station_timestamp(row["reference_timestamp"])
        except (KeyError, ValueError):
            continue
        has_value = False
        for column, species in POLLEN_PARAMS.items():
            value = _float(row.get(column))
            if value is None:
                continue
            has_value = True
            sums[species] = sums.get(species, 0.0) + value
            counts[species] = counts.get(species, 0) + 1
            current[species] = value
        if has_value and (newest is None or ts > newest):
            newest = ts
    if newest is None:
        raise OgdError(f"pollen file of {abbr} has no values")
    daily_mean = {s: round(sums[s] / counts[s], 1) for s in sums}
    return PollenReading(abbr=abbr, timestamp=newest, current=current, daily_mean=daily_mean, hours=max(counts.values(), default=0))


class PollenCoordinator(DataUpdateCoordinator[PollenReading]):
    """The pollen station's current day."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN} pollen", update_interval=UPDATE_INTERVAL, config_entry=entry)
        self.entry = entry
        self.station = str(entry.options.get(CONF_POLLEN_STATION, entry.data.get(CONF_POLLEN_STATION, "")))
        self.issues = IssueReporter(hass, entry.entry_id)

    async def _async_update_data(self) -> PollenReading:
        try:
            reading = await async_fetch_pollen_reading(async_get_clientsession(self.hass), self.station)
        except OgdError as err:
            self.issues.failure("pollen_unreadable", {"station": self.station, "error": str(err)})
            raise UpdateFailed(str(err)) from err
        self.issues.clear("pollen_unreadable")
        return reading

    @property
    def fresh(self) -> bool:
        return self.data is not None and dt_util.utcnow() - self.data.timestamp <= _MAX_AGE

    def level(self, species: str) -> str | None:
        return level_for(species, self.data.daily_mean.get(species)) if self.data else None

    def overall_level(self) -> str | None:
        if self.data is None:
            return None
        levels = [self.level(s) for s in SPECIES]
        levels = [lv for lv in levels if lv is not None]
        if not levels:
            return None
        return max(levels, key=LEVELS.index)
