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

from .const import ATTRIBUTION, DOMAIN, STATION_PARAMS
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
