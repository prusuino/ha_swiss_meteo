"""Swiss Meteo: MeteoSwiss local forecast and station data from the
official open data, read sparingly."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_POLLEN_STATION, CONF_STATION, CONF_WARNINGS, DOMAIN, STATION_PARAMS
from .coordinator import EntryData, ForecastCoordinator, StationCoordinator
from .device import entry_suffix
from .frontend import async_serve_frontend
from .history import GROUPS, HistoryError, async_import_history
from .pollen import PollenCoordinator
from .warnings import WarningsCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["weather", "sensor", "binary_sensor"]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_IMPORT_HISTORY = "import_history"
HOURLY_MAX_YEARS = 20  # hourly archive rows per import call (about 175 000 rows)
IMPORT_SCHEMA = vol.Schema(
    {
        vol.Required("entry"): cv.string,
        vol.Required("years", default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
        vol.Required("resolution", default="hourly"): vol.In(("hourly", "daily")),
        vol.Optional("values"): vol.All(cv.ensure_list, [vol.In(GROUPS)]),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the domain-level actions."""

    async def _import_history(call: ServiceCall) -> ServiceResponse:
        entry = hass.config_entries.async_get_entry(call.data["entry"])
        data: EntryData | None = hass.data.get(DOMAIN, {}).get(call.data["entry"])
        if entry is None or data is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_loaded")
        if data.station is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_station")
        if call.data["resolution"] == "hourly" and call.data["years"] > HOURLY_MAX_YEARS:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="hourly_years")
        groups = set(call.data.get("values") or GROUPS)
        units = {key: (unit or None) for _col, (key, unit) in STATION_PARAMS.items()}
        forecast = data.forecast

        def account(requests: int, nbytes: int) -> None:
            if forecast.data is not None:
                forecast._account(forecast.data, requests, nbytes)
                forecast.async_update_listeners()

        try:
            return await async_import_history(
                hass,
                station=data.station.station,
                entry_id=entry.entry_id,
                statistic_prefix=entry_suffix(entry),
                units=units,
                years=call.data["years"],
                resolution=call.data["resolution"],
                groups=groups,
                account=account,
            )
        except HistoryError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(DOMAIN, SERVICE_IMPORT_HISTORY, _import_history, schema=IMPORT_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    forecast = ForecastCoordinator(hass, entry)
    await forecast.async_config_entry_first_refresh()

    station: StationCoordinator | None = None
    if entry.options.get(CONF_STATION, entry.data.get(CONF_STATION)):
        station = StationCoordinator(hass, entry)
        # A station outage must not block the forecast: refresh without raising.
        await station.async_refresh()
        if not station.last_update_success:
            _LOGGER.warning("Entry %s: station %s not readable yet, its sensors start unavailable", entry_suffix(entry), station.station)

    pollen: PollenCoordinator | None = None
    if entry.options.get(CONF_POLLEN_STATION, entry.data.get(CONF_POLLEN_STATION)):
        pollen = PollenCoordinator(hass, entry)
        await pollen.async_refresh()
        if not pollen.last_update_success:
            _LOGGER.warning("Entry %s: pollen station %s not readable yet, its sensors start unavailable", entry_suffix(entry), pollen.station)

    warnings: WarningsCoordinator | None = None
    if entry.options.get(CONF_WARNINGS, entry.data.get(CONF_WARNINGS, True)):
        warnings = WarningsCoordinator(hass, entry)
        await warnings.async_refresh()
        if not warnings.last_update_success:
            _LOGGER.warning("Entry %s: warnings feed not readable yet, the warning entities start unavailable", entry_suffix(entry))

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = EntryData(forecast=forecast, station=station, pollen=pollen, warnings=warnings)
    await async_serve_frontend(hass)
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
