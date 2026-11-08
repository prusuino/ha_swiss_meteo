"""Sensors: the station's 10-minute values, a few figures from the
forecast (today's and tomorrow's high, low and precipitation), and
diagnostics (forecast run, station time, traffic)."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfIrradiance,
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, ATTRIBUTION_WARNINGS, DOMAIN, STATION_PARAMS
from .coordinator import EntryData, ForecastCoordinator, StationCoordinator
from .device import device_info, entry_suffix
from .derived import (
    HDD_BASE,
    HDD_THRESHOLD,
    day_mean,
    day_sum,
    heating_degree_days,
    hours_covered,
    next_rain,
    window_sum,
)
from .forecast import daily_values
from .localization import t
from .warnings import LEVELS as WARNING_LEVELS, WarningsCoordinator
from .pollen import LEVELS, SPECIES, PollenCoordinator

# key -> (device class, unit, state class, enabled by default, icon)
_STATION_META: dict[str, tuple] = {
    "temperature": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT, True, None),
    "temperature_5cm": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT, False, None),
    "dew_point": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT, True, "mdi:water-thermometer"),
    "humidity": (SensorDeviceClass.HUMIDITY, PERCENTAGE, SensorStateClass.MEASUREMENT, True, None),
    "pressure_qnh": (SensorDeviceClass.ATMOSPHERIC_PRESSURE, UnitOfPressure.HPA, SensorStateClass.MEASUREMENT, True, None),
    "pressure_qff": (SensorDeviceClass.ATMOSPHERIC_PRESSURE, UnitOfPressure.HPA, SensorStateClass.MEASUREMENT, False, None),
    "pressure_station": (SensorDeviceClass.PRESSURE, UnitOfPressure.HPA, SensorStateClass.MEASUREMENT, False, None),
    "wind_speed": (SensorDeviceClass.WIND_SPEED, UnitOfSpeed.KILOMETERS_PER_HOUR, SensorStateClass.MEASUREMENT, True, None),
    "wind_gust": (SensorDeviceClass.WIND_SPEED, UnitOfSpeed.KILOMETERS_PER_HOUR, SensorStateClass.MEASUREMENT, True, "mdi:weather-windy"),
    "wind_direction": (None, DEGREE, SensorStateClass.MEASUREMENT, True, "mdi:compass-outline"),
    "precipitation": (SensorDeviceClass.PRECIPITATION, UnitOfPrecipitationDepth.MILLIMETERS, SensorStateClass.MEASUREMENT, True, None),
    "sunshine": (SensorDeviceClass.DURATION, UnitOfTime.MINUTES, SensorStateClass.MEASUREMENT, True, "mdi:white-balance-sunny"),
    "global_radiation": (SensorDeviceClass.IRRADIANCE, UnitOfIrradiance.WATTS_PER_SQUARE_METER, SensorStateClass.MEASUREMENT, True, None),
    "diffuse_radiation": (SensorDeviceClass.IRRADIANCE, UnitOfIrradiance.WATTS_PER_SQUARE_METER, SensorStateClass.MEASUREMENT, False, None),
    "snow_depth": (SensorDeviceClass.DISTANCE, UnitOfLength.CENTIMETERS, SensorStateClass.MEASUREMENT, False, "mdi:snowflake"),
    "wind_chill": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT, False, "mdi:snowflake-thermometer"),
    "soil_temperature_5cm": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT, False, "mdi:thermometer-lines"),
    "soil_temperature_10cm": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT, False, "mdi:thermometer-lines"),
    "soil_temperature_20cm": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT, False, "mdi:thermometer-lines"),
    "surface_temperature": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT, False, "mdi:thermometer-low"),
    "vapour_pressure": (SensorDeviceClass.PRESSURE, UnitOfPressure.HPA, SensorStateClass.MEASUREMENT, False, "mdi:water-percent"),
    "wind_gust_3s": (SensorDeviceClass.WIND_SPEED, UnitOfSpeed.KILOMETERS_PER_HOUR, SensorStateClass.MEASUREMENT, False, "mdi:weather-windy"),
    "geopotential_850": (None, "gpm", SensorStateClass.MEASUREMENT, False, "mdi:altimeter"),
    "geopotential_700": (None, "gpm", SensorStateClass.MEASUREMENT, False, "mdi:altimeter"),
    "longwave_incoming": (SensorDeviceClass.IRRADIANCE, UnitOfIrradiance.WATTS_PER_SQUARE_METER, SensorStateClass.MEASUREMENT, False, "mdi:radiator"),
    "longwave_outgoing": (SensorDeviceClass.IRRADIANCE, UnitOfIrradiance.WATTS_PER_SQUARE_METER, SensorStateClass.MEASUREMENT, False, "mdi:radiator-disabled"),
    "reflected_radiation": (SensorDeviceClass.IRRADIANCE, UnitOfIrradiance.WATTS_PER_SQUARE_METER, SensorStateClass.MEASUREMENT, False, "mdi:white-balance-sunny"),
    "foehn_index": (None, None, SensorStateClass.MEASUREMENT, False, "mdi:weather-windy-variant"),
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data: EntryData = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    if data.station is not None:
        for column, (key, _unit) in STATION_PARAMS.items():
            entities.append(StationSensor(hass, entry, data.station, column, key))
        entities.append(StationTimeSensor(hass, entry, data.station))
    for day_key in ("today", "tomorrow"):
        for what in ("max", "min", "precipitation"):
            entities.append(DayValueSensor(hass, entry, data.forecast, day_key, what))
    for key in DERIVED_KEYS:
        if not data.forecast.hourly_enabled and key not in _DAILY_ONLY_KEYS:
            continue
        entities.append(DerivedSensor(hass, entry, data.forecast, key))
    if data.pollen is not None:
        for species in SPECIES:
            entities.append(PollenSensor(hass, entry, data.pollen, species))
        entities.append(PollenLevelSensor(hass, entry, data.pollen))
    if data.warnings is not None:
        entities.append(WarningLevelSensor(hass, entry, data.warnings))
    entities.append(ForecastRunSensor(hass, entry, data.forecast))
    entities.append(TrafficSensor(hass, entry, data.forecast))
    async_add_entities(entities)


class _Base(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = t(key, hass)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info(hass, entry)
        self.entity_id = f"sensor.{DOMAIN}_{entry_suffix(entry)}_{key}"


class StationSensor(_Base):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: StationCoordinator, column: str, key: str) -> None:
        super().__init__(hass, entry, coordinator, key)
        self._column = column
        device_class, unit, state_class, enabled, icon = _STATION_META[key]
        if device_class is not None:
            self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = state_class
        self._attr_entity_registry_enabled_default = enabled
        if icon:
            self._attr_icon = icon

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.fresh

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.values.get(self._column)


class StationTimeSensor(_Base):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: StationCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "station_time")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.timestamp if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict:
        return {"station": self.coordinator.station, "fresh": self.coordinator.fresh}


class DayValueSensor(_Base):
    """Today's / tomorrow's high, low or precipitation from the daily forecast."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator, day_key: str, what: str) -> None:
        super().__init__(hass, entry, coordinator, f"{day_key}_{what}")
        self._offset = 0 if day_key == "today" else 1
        self._what = what
        if what == "precipitation":
            self._attr_device_class = SensorDeviceClass.PRECIPITATION
            self._attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
            self._attr_icon = "mdi:weather-rainy"
        else:
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_icon = "mdi:thermometer-chevron-up" if what == "max" else "mdi:thermometer-chevron-down"

    @property
    def native_value(self) -> float | None:
        snap = self.coordinator.data
        if snap is None:
            return None
        param = {"max": "tre200px", "min": "tre200pn", "precipitation": "rka150p0"}[self._what]
        day = dt_util.now().date()
        if self._offset:
            day = day + timedelta(days=self._offset)
        return daily_values(snap, param).get(day)


# key -> (device class, unit, icon, enabled by default)
_DERIVED_META: dict[str, tuple] = {
    "today_mean": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, "mdi:thermometer", True),
    "tomorrow_mean": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, "mdi:thermometer", True),
    "heating_degree_days_today": (None, "K·d", "mdi:radiator", True),
    "heating_degree_days_tomorrow": (None, "K·d", "mdi:radiator", True),
    "radiation_today": (None, "kWh/m²", "mdi:solar-power-variant", True),
    "radiation_tomorrow": (None, "kWh/m²", "mdi:solar-power-variant", True),
    "sunshine_today": (SensorDeviceClass.DURATION, UnitOfTime.HOURS, "mdi:white-balance-sunny", True),
    "sunshine_tomorrow": (SensorDeviceClass.DURATION, UnitOfTime.HOURS, "mdi:white-balance-sunny", True),
    "precipitation_next_24h": (SensorDeviceClass.PRECIPITATION, UnitOfPrecipitationDepth.MILLIMETERS, "mdi:weather-pouring", True),
    "next_rain": (SensorDeviceClass.TIMESTAMP, None, "mdi:weather-rainy", True),
}
DERIVED_KEYS = tuple(_DERIVED_META)
# These work from the daily files alone (mean from high and low).
_DAILY_ONLY_KEYS = ("today_mean", "tomorrow_mean", "heating_degree_days_today", "heating_degree_days_tomorrow")


class DerivedSensor(_Base):
    """A figure computed from the forecast series: daily mean and heating
    degree days (SIA 381/3, 12/20), global radiation and sunshine sums,
    the precipitation of the next 24 hours, the next hour with rain."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator, key: str) -> None:
        super().__init__(hass, entry, coordinator, key)
        self._key = key
        device_class, unit, icon, enabled = _DERIVED_META[key]
        if device_class is not None:
            self._attr_device_class = device_class
        if unit is not None:
            self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_entity_registry_enabled_default = enabled
        if device_class != SensorDeviceClass.TIMESTAMP:
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_suggested_display_precision = 1

    def _day(self):
        day = dt_util.now().date()
        return day + timedelta(days=1) if self._key.endswith("_tomorrow") else day

    @property
    def native_value(self):
        snap = self.coordinator.data
        if snap is None:
            return None
        key = self._key
        if key in ("today_mean", "tomorrow_mean"):
            return day_mean(snap, self._day())
        if key.startswith("heating_degree_days"):
            return heating_degree_days(day_mean(snap, self._day()))
        if key.startswith("radiation"):
            total = day_sum(snap, "gre000h0", self._day())  # W/m² hourly means -> Wh/m²
            return round(total / 1000, 2) if total is not None else None
        if key.startswith("sunshine"):
            total = day_sum(snap, "sre000h0", self._day())  # minutes
            return round(total / 60, 1) if total is not None else None
        if key == "precipitation_next_24h":
            return window_sum(snap.hourly.get("rre150h0"), 24)
        if key == "next_rain":
            hit = next_rain(snap)
            return hit[0] if hit else None
        return None

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.data
        if snap is None:
            return {}
        key = self._key
        if key.startswith("heating_degree_days"):
            return {"threshold": HDD_THRESHOLD, "base": HDD_BASE, "mean_temperature": day_mean(snap, self._day())}
        if key.startswith(("radiation", "sunshine", "today_mean", "tomorrow_mean")):
            return {"hours_in_forecast": hours_covered(snap, self._day())}
        if key == "next_rain":
            hit = next_rain(snap)
            if hit is None:
                return {}
            return {"precipitation_mm": hit[1], "hours_until": max(0, round((hit[0] - dt_util.utcnow()).total_seconds() / 3600))}
        return {}


class PollenSensor(_Base):
    """The newest hourly concentration of one species, with the day's mean
    and the MeteoSwiss load class as attributes."""

    _attr_native_unit_of_measurement = "pollen/m³"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flower-pollen"
    _attr_suggested_display_precision = 0

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: PollenCoordinator, species: str) -> None:
        super().__init__(hass, entry, coordinator, f"pollen_{species}")
        self._species = species

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.fresh

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.current.get(self._species) if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "station": data.abbr,
            "measured": data.timestamp.isoformat(),
            "daily_mean": data.daily_mean.get(self._species),
            "hours_today": data.hours,
            "level": self.coordinator.level(self._species),
        }


class PollenLevelSensor(_Base):
    """The highest MeteoSwiss load class over the seven species, from the
    day's mean concentrations."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(LEVELS)
    _attr_translation_key = "pollen_level"
    _attr_icon = "mdi:flower-pollen-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: PollenCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "pollen_level")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.fresh

    @property
    def native_value(self) -> str | None:
        return self.coordinator.overall_level()

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if data is None:
            return {}
        attrs: dict = {"station": data.abbr, "measured": data.timestamp.isoformat()}
        for species in SPECIES:
            attrs[species] = self.coordinator.level(species)
        attrs["highest"] = [s for s in SPECIES if self.coordinator.level(s) == self.coordinator.overall_level()]
        return attrs


class WarningLevelSensor(_Base):
    """The highest MeteoAlarm colour of the official warnings in force for
    the forecast point: none, yellow, orange, red. The warnings themselves
    (in force and announced) are attributes."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(WARNING_LEVELS)
    _attr_translation_key = "warning_level"
    _attr_icon = "mdi:alert-outline"
    _attr_attribution = ATTRIBUTION_WARNINGS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: WarningsCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "warning_level")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.fresh

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.level() if self.coordinator.data else None

    @property
    def icon(self) -> str:
        level = self.native_value
        return "mdi:alert-outline" if level in (None, "none") else "mdi:alert"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if data is None:
            return {}
        active = data.active
        upcoming = data.upcoming
        return {
            "count": len(active),
            "upcoming": len(upcoming),
            "highest_upcoming": max((w.level for w in upcoming), key=WARNING_LEVELS.index) if upcoming else "none",
            "next_onset": min((w.onset for w in upcoming if w.onset), default=None).isoformat() if any(w.onset for w in upcoming) else None,
            "warnings": [w.as_dict() for w in data.items],
            "feed_alerts": data.total,
            "fetched": data.fetched.isoformat(),
        }


class ForecastRunSensor(_Base):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "forecast_run")

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.run if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.data
        if snap is None:
            return {}
        return {
            "daily_fetched": snap.daily_fetched.isoformat() if snap.daily_fetched else None,
            "hourly_fetched": snap.hourly_fetched.isoformat() if snap.hourly_fetched else None,
            "parameters_daily": sorted(snap.daily),
            "parameters_hourly": sorted(snap.hourly),
            "missing": snap.missing,
        }


class TrafficSensor(_Base):
    """Megabytes read from MeteoSwiss since local midnight: the integration
    reads slices of large files, and this shows that it stays small."""

    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = "MB"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:download-network-outline"
    _attr_suggested_display_precision = 2

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "traffic_today")

    @property
    def native_value(self) -> float | None:
        snap = self.coordinator.data
        return round(snap.bytes_today / 1_000_000, 3) if snap else None

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.data
        if snap is None:
            return {}
        return {
            "requests_today": snap.requests_today,
            "last_read_requests": snap.last_requests,
            "last_read_bytes": snap.last_bytes,
        }
