"""Binary sensors: rain expected within the next hours, frost tonight and
the everyday questions — laundry weather, frozen windscreen tomorrow
morning, cool night after a hot day, watering needed (all from the hourly
forecast; without it they stay unavailable) — and an official warning in
force (from the MeteoAlarm feed)."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, ATTRIBUTION_WARNINGS, CONF_GUST_THRESHOLD, DEFAULT_GUST_THRESHOLD, DOMAIN
from .coordinator import EntryData, ForecastCoordinator
from .derived import (
    COOL_NIGHT_MAX,
    DRYING_HOURS,
    DRYING_MAX_PROBABILITY,
    DRYING_MIN_TEMPERATURE,
    HOT_DAY_MIN,
    RAIN_THRESHOLD_MM,
    WATERING_HOURS,
    WATERING_MAX_RAIN,
    WATERING_MIN_HIGH,
    WIND_WINDOW_HOURS,
    WINDSCREEN_THRESHOLD,
    drying_window,
    max_gust,
    morning_minimum,
    next_rain,
    night_minimum,
    todays_high,
    window_sum,
)
from .device import device_info, entry_suffix
from .meteoalarm import WarningsCoordinator
from .radar import RadarCoordinator

RAIN_WINDOW_HOURS = 6
FROST_THRESHOLD = 0.0


# The coordinators do the reading; the entities only show what they hold.
PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data: EntryData = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    if data.forecast.hourly_enabled:
        entities += [RainExpectedSensor(hass, entry, data.forecast), FrostTonightSensor(hass, entry, data.forecast), StrongWindExpectedSensor(hass, entry, data.forecast)]
        entities += [cls(hass, entry, data.forecast) for cls in (LaundryWeatherSensor, FrozenWindscreenSensor, CoolNightSensor, WateringNeededSensor)]
    if data.warnings is not None:
        entities.append(WarningActiveSensor(hass, entry, data.warnings))
    if data.radar is not None:
        entities += [RainingSensor(hass, entry, data.radar), RainApproachingSensor(hass, entry, data.radar)]
    async_add_entities(entities)


class _Base(CoordinatorEntity[ForecastCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info(hass, entry)
        self.entity_id = f"binary_sensor.{DOMAIN}_{entry_suffix(entry)}_{key}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The state depends on the clock as well as on the data: re-evaluate
        # every full hour so "within 6 hours" slides along without a new run.
        self.async_on_remove(async_track_time_change(self.hass, self._tick, minute=0, second=30))

    @callback
    def _tick(self, _now) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data and self.coordinator.data.hourly)


class RainExpectedSensor(_Base):
    """On when at least 0.1 mm of precipitation is forecast for one of the
    next six hours."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "rain_expected")

    @property
    def is_on(self) -> bool | None:
        snap = self.coordinator.data
        if snap is None:
            return None
        hit = next_rain(snap)
        if hit is None:
            return False
        return hit[0] < dt_util.utcnow() + timedelta(hours=RAIN_WINDOW_HOURS)

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.data
        if snap is None:
            return {}
        hit = next_rain(snap)
        attrs = {
            "window_hours": RAIN_WINDOW_HOURS,
            "threshold_mm": RAIN_THRESHOLD_MM,
            "precipitation_next_6h": window_sum(snap.hourly.get("rre150h0"), RAIN_WINDOW_HOURS),
            "precipitation_next_24h": window_sum(snap.hourly.get("rre150h0"), 24),
        }
        if hit is not None:
            attrs["next_rain"] = dt_util.as_local(hit[0]).isoformat()
            attrs["next_rain_mm"] = hit[1]
            attrs["hours_until_rain"] = max(0, round((hit[0] - dt_util.utcnow()).total_seconds() / 3600))
        return attrs


class FrostTonightSensor(_Base):
    """On when the hourly forecast drops to 0 °C or below between now and
    09:00 of the next morning."""

    _attr_device_class = BinarySensorDeviceClass.COLD

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "frost_tonight")

    @property
    def is_on(self) -> bool | None:
        snap = self.coordinator.data
        if snap is None:
            return None
        low = night_minimum(snap)
        return low is not None and low[1] <= FROST_THRESHOLD

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.data
        if snap is None:
            return {}
        low = night_minimum(snap)
        if low is None:
            return {"threshold": FROST_THRESHOLD}
        return {
            "threshold": FROST_THRESHOLD,
            "night_minimum": low[1],
            "night_minimum_at": dt_util.as_local(low[0]).isoformat(),
        }


class StrongWindExpectedSensor(_Base):
    """On when the hourly forecast has a gust peak at or above the configured
    threshold (60 km/h by default) within the next six hours."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "strong_wind_expected")
        self._threshold = float(entry.options.get(CONF_GUST_THRESHOLD, entry.data.get(CONF_GUST_THRESHOLD, DEFAULT_GUST_THRESHOLD)))

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data or not self.coordinator.data.hourly:
            return None
        peak = max_gust(self.coordinator.data)
        return bool(peak and peak[1] >= self._threshold)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        peak = max_gust(self.coordinator.data)
        return {
            "threshold_kmh": self._threshold,
            "window_hours": WIND_WINDOW_HOURS,
            "max_gust": peak[1] if peak else None,
            "max_gust_at": peak[0].isoformat() if peak else None,
        }


class WarningActiveSensor(CoordinatorEntity[WarningsCoordinator], BinarySensorEntity):
    """On while an official warning (MeteoAlarm) is in force for the
    forecast point."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION_WARNINGS
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: WarningsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = "warning_active"
        self._attr_unique_id = f"{entry.entry_id}_warning_active"
        self._attr_device_info = device_info(hass, entry)
        self.entity_id = f"binary_sensor.{DOMAIN}_{entry_suffix(entry)}_warning_active"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.fresh

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return bool(data.active) if data else None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        if data is None:
            return {}
        return {"level": data.level(), "count": len(data.active), "upcoming": len(data.upcoming), "warnings": data.as_list(brief=True)}


class _RadarBinary(CoordinatorEntity[RadarCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: RadarCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info(hass, entry)
        self.entity_id = f"binary_sensor.{DOMAIN}_{entry_suffix(entry)}_{key}"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.fresh

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data
        if d is None:
            return {}
        return {"rain_rate": d.rate, "nearest_rain_km": d.nearest_km, "eta_min": d.eta_min, "speed_kmh": d.speed_kmh, "direction": d.direction, "radar_time": d.frame_ts.isoformat()}


class RainingSensor(_RadarBinary):
    """On while the radar shows rain at the point (0.1 mm/h or more within 1 km)."""


    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: RadarCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "raining")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.raining if self.coordinator.data else None


class RainApproachingSensor(_RadarBinary):
    """On while it rains or rain is estimated to reach the point within 30 minutes."""


    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: RadarCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "rain_approaching")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.approaching if self.coordinator.data else None


class LaundryWeatherSensor(_Base):
    """On while today still has four dry hours in a row between 08:00 and
    20:00: no precipitation, at most a 30 % chance of rain, 5 °C or more."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "laundry_weather")

    @property
    def is_on(self) -> bool | None:
        snap = self.coordinator.data
        if snap is None:
            return None
        window = drying_window(snap)
        return bool(window and window["hours"] >= DRYING_HOURS)

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.data
        window = drying_window(snap) if snap else None
        return {
            "required_hours": DRYING_HOURS,
            "max_rain_probability": DRYING_MAX_PROBABILITY,
            "min_temperature": DRYING_MIN_TEMPERATURE,
            "dry_hours": window["hours"] if window else 0,
            "window_start": window["start"] if window else None,
            "window_end": window["end"] if window else None,
        }


class FrozenWindscreenSensor(_Base):
    """On when the hourly forecast is at 1 °C or below between 04:00 and
    08:00 of the coming morning: ice on the windscreen is likely. It has no
    device class on purpose: the frost trigger and condition pick their
    entity by the class "cold", which stays the frost sensor's alone."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "frozen_windscreen")

    @property
    def is_on(self) -> bool | None:
        snap = self.coordinator.data
        if snap is None:
            return None
        low = morning_minimum(snap)
        return low is not None and low[1] <= WINDSCREEN_THRESHOLD

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.data
        low = morning_minimum(snap) if snap else None
        return {
            "threshold": WINDSCREEN_THRESHOLD,
            "morning_minimum": low[1] if low else None,
            "morning_minimum_at": dt_util.as_local(low[0]).isoformat() if low else None,
        }


class CoolNightSensor(_Base):
    """On when a hot day (25 °C or more) is followed by a cool night (17 °C
    or less before 09:00): airing at night cools the house."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "cool_night")

    @property
    def is_on(self) -> bool | None:
        snap = self.coordinator.data
        if snap is None:
            return None
        low, high = night_minimum(snap), todays_high(snap)
        return low is not None and high is not None and high >= HOT_DAY_MIN and low[1] <= COOL_NIGHT_MAX

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.data
        low = night_minimum(snap) if snap else None
        return {
            "hot_day_from": HOT_DAY_MIN,
            "cool_night_up_to": COOL_NIGHT_MAX,
            "today_high": todays_high(snap) if snap else None,
            "night_minimum": low[1] if low else None,
            "night_minimum_at": dt_util.as_local(low[0]).isoformat() if low else None,
        }


class WateringNeededSensor(_Base):
    """On when today reaches 20 °C or more and less than 2 mm of rain is
    forecast for the next 48 hours. It looks ahead only: how much it rained
    before is not known to it."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator) -> None:
        super().__init__(hass, entry, coordinator, "watering_needed")

    @property
    def is_on(self) -> bool | None:
        snap = self.coordinator.data
        if snap is None:
            return None
        rain, high = window_sum(snap.hourly.get("rre150h0"), WATERING_HOURS), todays_high(snap)
        return rain is not None and high is not None and high >= WATERING_MIN_HIGH and rain < WATERING_MAX_RAIN

    @property
    def extra_state_attributes(self) -> dict:
        snap = self.coordinator.data
        return {
            "window_hours": WATERING_HOURS,
            "max_rain_mm": WATERING_MAX_RAIN,
            "warm_day_from": WATERING_MIN_HIGH,
            "precipitation_next_48h": window_sum(snap.hourly.get("rre150h0"), WATERING_HOURS) if snap else None,
            "today_high": todays_high(snap) if snap else None,
        }
