"""Binary sensors from the hourly forecast: rain expected within the next
hours, frost expected tonight. They need the hourly forecast (on by
default); without it they stay unavailable."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import ATTRIBUTION, DOMAIN
from .coordinator import EntryData, ForecastCoordinator
from .derived import RAIN_THRESHOLD_MM, next_rain, night_minimum, window_sum
from .device import device_info, entry_suffix
from .localization import t

RAIN_WINDOW_HOURS = 6
FROST_THRESHOLD = 0.0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data: EntryData = hass.data[DOMAIN][entry.entry_id]
    if not data.forecast.hourly_enabled:
        return
    async_add_entities([RainExpectedSensor(hass, entry, data.forecast), FrostTonightSensor(hass, entry, data.forecast)])


class _Base(CoordinatorEntity[ForecastCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: ForecastCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_name = t(key, hass)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = device_info(hass, entry)
        self.entity_id = f"binary_sensor.{DOMAIN}_{entry_suffix(entry)}_{key}"
        self._unsub_timer = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The state depends on the clock as well as on the data: re-evaluate
        # every full hour so "within 6 hours" slides along without a new run.
        from homeassistant.helpers.event import async_track_time_change

        self._unsub_timer = async_track_time_change(self.hass, self._tick, minute=0, second=30)

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        await super().async_will_remove_from_hass()

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
