"""Swiss Meteo: MeteoSwiss local forecast and station data from the
official open data, read sparingly."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import CONF_POLLEN_STATION, CONF_RADAR, CONF_STATION, CONF_WARNINGS, DOMAIN, STATION_PARAMS
from .coordinator import EntryData, ForecastCoordinator, StationCoordinator
from .device import entry_suffix
from .frontend import async_serve_frontend
from .derived import best_window
from .history import GROUPS, HistoryError, async_import_history
from .pollen import PollenCoordinator
from .meteoalarm import WarningsCoordinator
from .radar import RadarCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["weather", "sensor", "binary_sensor", "image"]
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

SERVICE_BEST_WINDOW = "best_window"
WINDOW_SCHEMA = vol.Schema(
    {
        vol.Required("entry"): cv.string,
        vol.Required("hours", default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
        vol.Required("within", default=24): vol.All(vol.Coerce(int), vol.Range(min=3, max=48)),
        vol.Required("criterion", default="dry"): vol.In(("dry", "sunny", "calm")),
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

    async def _best_window(call: ServiceCall) -> ServiceResponse:
        data: EntryData | None = hass.data.get(DOMAIN, {}).get(call.data["entry"])
        if data is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_loaded")
        snap = data.forecast.data
        if snap is None or not snap.hourly:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_hourly")
        result = best_window(snap, call.data["hours"], call.data["within"], call.data["criterion"])
        return result or {"found": False, "criterion": call.data["criterion"]}

    hass.services.async_register(DOMAIN, SERVICE_BEST_WINDOW, _best_window, schema=WINDOW_SCHEMA, supports_response=SupportsResponse.ONLY)
    websocket_api.async_register_command(hass, ws_radar_frames)
    return True


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/radar_frames", vol.Required("entity_id"): cv.entity_id})
@websocket_api.async_response
async def ws_radar_frames(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """The radar loop (past frames and extrapolated ones) of the entry an
    entity belongs to, for the radar card."""
    registry = er.async_get(hass)
    ent = registry.async_get(msg["entity_id"])
    data: EntryData | None = hass.data.get(DOMAIN, {}).get(ent.config_entry_id) if ent and ent.config_entry_id else None
    if data is None or data.radar is None:
        connection.send_error(msg["id"], "not_found", "No radar for this entity (radar off or entity not from Swiss Meteo)")
        return
    connection.send_result(msg["id"], await data.radar.async_frames_for_card())


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

    radar: RadarCoordinator | None = None
    if entry.options.get(CONF_RADAR, entry.data.get(CONF_RADAR, True)):
        def _account_radar(requests: int, nbytes: int) -> None:
            if forecast.data is not None:
                forecast._account(forecast.data, requests, nbytes)

        try:
            radar = RadarCoordinator(hass, entry, _account_radar)
        except ValueError:
            _LOGGER.warning("Entry %s: point outside the radar composite, radar disabled", entry_suffix(entry))
        else:
            await radar.async_refresh()
            if not radar.last_update_success:
                _LOGGER.warning("Entry %s: radar not readable yet, its entities start unavailable", entry_suffix(entry))

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = EntryData(forecast=forecast, station=station, pollen=pollen, warnings=warnings, radar=radar)
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
