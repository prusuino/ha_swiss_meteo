"""Swiss Meteo: MeteoSwiss local forecast and station data from the
official open data, read sparingly."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_STATION, DOMAIN
from .coordinator import EntryData, ForecastCoordinator, StationCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["weather", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    forecast = ForecastCoordinator(hass, entry)
    await forecast.async_config_entry_first_refresh()

    station: StationCoordinator | None = None
    if entry.options.get(CONF_STATION, entry.data.get(CONF_STATION)):
        station = StationCoordinator(hass, entry)
        # A station outage must not block the forecast: refresh without raising.
        await station.async_refresh()
        if not station.last_update_success:
            _LOGGER.warning("%s: station %s not readable yet, its sensors start unavailable", entry.title, station.station)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = EntryData(forecast=forecast, station=station)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
