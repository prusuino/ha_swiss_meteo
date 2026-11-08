"""Binary sensors: rain expected within the next hours and frost tonight
(from the hourly forecast; without it they stay unavailable), and an
official warning in force (from the MeteoAlarm feed)."""
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

from .const import ATTRIBUTION, ATTRIBUTION_WARNINGS, DOMAIN
from .coordinator import EntryData, ForecastCoordinator
from .derived import RAIN_THRESHOLD_MM, next_rain, night_minimum, window_sum
from .device import device_info, entry_suffix
from .localization import t
from .meteoalarm import WarningsCoordinator

RAIN_WINDOW_HOURS = 6
FROST_THRESHOLD = 0.0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data: EntryData = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []
    if data.forecast.hourly_enabled:
        entities += [RainExpectedSensor(hass, entry, data.forecast), FrostTonightSensor(hass, entry, data.forecast)]
    if data.warnings is not None:
        entities.append(WarningActiveSensor(hass, entry, data.warnings))
    async_add_entities(entities)


class _Base(CoordinatorEntity[ForecastCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_name = t(key, hass)
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
    _attr_icon = "mdi:weather-rainy"

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
    _attr_icon = "mdi:snowflake-alert"

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


class WarningActiveSensor(CoordinatorEntity[WarningsCoordinator], BinarySensorEntity):
    """On while an official warning (MeteoAlarm) is in force for the
    forecast point."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION_WARNINGS
    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_icon = "mdi:alert-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: WarningsCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = t("warning_active", hass)
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
