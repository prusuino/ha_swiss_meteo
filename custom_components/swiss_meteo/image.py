"""Image entity: the newest radar frame around the forecast point as a
PNG (200 × 200 km, 1 km per pixel, rain-rate colours), for the picture
cards of Home Assistant. The radar card of the integration plays the
whole loop; this entity is the still."""
from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import EntryData
from .device import device_info, entry_suffix
from .localization import t
from .radar import RadarCoordinator


# The coordinators do the reading; the entities only show what they hold.
PARALLEL_UPDATES = 0


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data: EntryData = entry.runtime_data
    if data.radar is not None:
        async_add_entities([RadarImage(hass, entry, data.radar)])


class RadarImage(CoordinatorEntity[RadarCoordinator], ImageEntity):
    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _attr_content_type = "image/png"
    _attr_icon = "mdi:radar"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator: RadarCoordinator) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, hass)
        self._attr_name = t("radar_image", hass)
        self._attr_unique_id = f"{entry.entry_id}_radar_image"
        self._attr_device_info = device_info(hass, entry)
        self.entity_id = f"image.{DOMAIN}_{entry_suffix(entry)}_radar"
        self._attr_image_last_updated = coordinator.data.frame_ts if coordinator.data else None

    def _handle_coordinator_update(self) -> None:
        if self.coordinator.data:
            self._attr_image_last_updated = self.coordinator.data.frame_ts
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.fresh

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data
        if d is None:
            return {}
        e_km, n_km = self.coordinator.origin_km
        return {"radar_time": d.frame_ts.isoformat(), "km_per_pixel": 1, "origin_lv95_km": [e_km, n_km], "rain_rate": d.rate}

    async def async_image(self) -> bytes | None:
        return await self.hass.async_add_executor_job(self.coordinator.latest_png)
