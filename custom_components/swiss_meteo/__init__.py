"""Swiss Meteo: MeteoSwiss local forecast and station data from the
official open data, read sparingly."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .issues import async_clear_entry_issues
from .const import CONF_OPEN_METEO, CONF_POLLEN_STATION, CONF_PRECIP_STATION, CONF_RADAR, CONF_STATION, CONF_WARNINGS, DOMAIN, STATION_PARAMS
from .climatology import ClimateCoordinator, climate_store
from .coordinator import EntryData, ForecastCoordinator, PrecipCoordinator, StationCoordinator, hints_store
from .device import entry_suffix, open_meteo_identifier
from .frontend import async_serve_frontend
from .derived import best_window
from .history import GROUPS, HistoryError, async_import_history
from .open_meteo import OpenMeteoCoordinator
from .pollen import PollenCoordinator
from .meteoalarm import WarningsCoordinator
from .national import national, warning_areas
from .radar import RadarCoordinator

type SwissMeteoConfigEntry = ConfigEntry[EntryData]

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
        data: EntryData | None = getattr(entry, "runtime_data", None) if entry else None
        if entry is None or data is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_loaded")
        if data.station is None and data.precip is None:
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
                station=data.station.station if data.station else "",
                precip_station=data.precip.station if data.precip else "",
                entry_id=entry.entry_id,
                statistic_prefix=entry_suffix(entry),
                units=units,
                years=call.data["years"],
                resolution=call.data["resolution"],
                groups=groups,
                account=account,
            )
        except HistoryError as err:
            raise HomeAssistantError(str(err), translation_domain=DOMAIN, translation_key="history_import_failed", translation_placeholders={"error": str(err)}) from err

    hass.services.async_register(DOMAIN, SERVICE_IMPORT_HISTORY, _import_history, schema=IMPORT_SCHEMA, supports_response=SupportsResponse.OPTIONAL)

    async def _best_window(call: ServiceCall) -> ServiceResponse:
        entry = hass.config_entries.async_get_entry(call.data["entry"])
        data: EntryData | None = getattr(entry, "runtime_data", None) if entry else None
        if data is None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_loaded")
        snap = data.forecast.data
        if snap is None or not snap.hourly:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_hourly")
        result = best_window(snap, call.data["hours"], call.data["within"], call.data["criterion"])
        return result or {"found": False, "criterion": call.data["criterion"]}

    hass.services.async_register(DOMAIN, SERVICE_BEST_WINDOW, _best_window, schema=WINDOW_SCHEMA, supports_response=SupportsResponse.ONLY)
    websocket_api.async_register_command(hass, ws_radar_frames)
    websocket_api.async_register_command(hass, ws_map)
    websocket_api.async_register_command(hass, ws_climate)
    return True


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/radar_frames", vol.Required("entity_id"): cv.entity_id})
@websocket_api.async_response
async def ws_radar_frames(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """The radar loop (past frames and extrapolated ones) of the entry an
    entity belongs to, for the radar card."""
    registry = er.async_get(hass)
    ent = registry.async_get(msg["entity_id"])
    entry = hass.config_entries.async_get_entry(ent.config_entry_id) if ent and ent.config_entry_id else None
    data: EntryData | None = getattr(entry, "runtime_data", None) if entry else None
    if data is None or data.radar is None:
        connection.send_error(msg["id"], "not_found", "No radar for this entity (radar off or entity not from Swiss Meteo)")
        return
    connection.send_result(msg["id"], await data.radar.async_frames_for_card())


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/climate", vol.Required("entity_id"): cv.entity_id})
@callback
def ws_climate(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """The station's yearly means of the entry an entity belongs to, for the
    climate stripes card. Nothing is read: they come from the stored table."""
    ent = er.async_get(hass).async_get(msg["entity_id"])
    entry = hass.config_entries.async_get_entry(ent.config_entry_id) if ent and ent.config_entry_id else None
    data: EntryData | None = getattr(entry, "runtime_data", None) if entry else None
    stripes = data.climate.stripes() if data is not None and data.climate is not None else None
    if stripes is None:
        connection.send_error(msg["id"], "not_found", "No climate figures for this entity (no station, or the archive is not read yet)")
        return
    connection.send_result(msg["id"], stripes)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/map", vol.Required("layer"): vol.In(("weather", "warnings", "radar"))})
@websocket_api.async_response
async def ws_map(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """A layer of the map of Switzerland. What it reads counts towards the
    traffic of the first loaded entry."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "not_found", "No Swiss Meteo entry is loaded")
        return
    if msg["layer"] == "warnings":
        feeds = [e.runtime_data.warnings for e in entries if e.runtime_data.warnings is not None]
        feed = next((c for c in feeds if c.feed is not None and c.fresh), None)
        areas = await hass.async_add_executor_job(warning_areas, feed.feed, dt_util.utcnow()) if feed else []
        connection.send_result(msg["id"], {"enabled": bool(feeds), "available": feed is not None, "warnings": areas})
        return
    forecast = entries[0].runtime_data.forecast

    def account(requests: int, nbytes: int) -> None:
        if forecast.data is not None:
            forecast._account(forecast.data, requests, nbytes)

    data = national(hass)
    result = await (data.async_forecast(account) if msg["layer"] == "weather" else data.async_radar(account))
    connection.send_result(msg["id"], result)


async def async_setup_entry(hass: HomeAssistant, entry: SwissMeteoConfigEntry) -> bool:
    forecast = ForecastCoordinator(hass, entry)
    await forecast.async_config_entry_first_refresh()

    def _account(requests: int, nbytes: int) -> None:
        """What a feed of this entry transferred, for the traffic sensor."""
        if forecast.data is not None:
            forecast._account(forecast.data, requests, nbytes)

    station: StationCoordinator | None = None
    if entry.options.get(CONF_STATION, entry.data.get(CONF_STATION)):
        station = StationCoordinator(hass, entry, _account)
        # A station outage must not block the forecast: refresh without raising.
        await station.async_refresh()
        if not station.last_update_success:
            _LOGGER.warning("Entry %s: station %s not readable yet, its sensors start unavailable", entry_suffix(entry), station.station)

    climate: ClimateCoordinator | None = None
    if station is not None:
        # The station's normals and records. The archive behind them is large
        # and read once; it must not hold up the setup, so it is read after it.
        climate = ClimateCoordinator(hass, entry, _account)
        entry.async_create_background_task(hass, climate.async_refresh(), f"{DOMAIN} climate first read")
        # the normal and the records are those of the calendar day
        day_climate = climate

        async def _new_day(_now) -> None:
            await day_climate.async_request_refresh()

        entry.async_on_unload(async_track_time_change(hass, _new_day, hour=0, minute=1, second=0))

    precip: PrecipCoordinator | None = None
    if entry.options.get(CONF_PRECIP_STATION, entry.data.get(CONF_PRECIP_STATION)):
        precip = PrecipCoordinator(hass, entry, _account)
        await precip.async_refresh()
        if not precip.last_update_success:
            _LOGGER.warning("Entry %s: precipitation station %s not readable yet, its sensor starts unavailable", entry_suffix(entry), precip.station)

    pollen: PollenCoordinator | None = None
    if entry.options.get(CONF_POLLEN_STATION, entry.data.get(CONF_POLLEN_STATION)):
        pollen = PollenCoordinator(hass, entry, _account)
        await pollen.async_refresh()
        if not pollen.last_update_success:
            _LOGGER.warning("Entry %s: pollen station %s not readable yet, its sensors start unavailable", entry_suffix(entry), pollen.station)

    warnings: WarningsCoordinator | None = None
    if entry.options.get(CONF_WARNINGS, entry.data.get(CONF_WARNINGS, True)):
        warnings = WarningsCoordinator(hass, entry, _account)
        await warnings.async_refresh()
        if not warnings.last_update_success:
            _LOGGER.warning("Entry %s: warnings feed not readable yet, the warning entities start unavailable", entry_suffix(entry))

    radar: RadarCoordinator | None = None
    if entry.options.get(CONF_RADAR, entry.data.get(CONF_RADAR, True)):
        try:
            radar = RadarCoordinator(hass, entry, _account)
        except ValueError:
            _LOGGER.warning("Entry %s: point outside the radar composite, radar disabled", entry_suffix(entry))
        else:
            await radar.async_refresh()
            if not radar.last_update_success:
                _LOGGER.warning("Entry %s: radar not readable yet, its entities start unavailable", entry_suffix(entry))

    open_meteo: OpenMeteoCoordinator | None = None
    if entry.options.get(CONF_OPEN_METEO, entry.data.get(CONF_OPEN_METEO, False)):
        open_meteo = OpenMeteoCoordinator(hass, entry, _account)
        await open_meteo.async_refresh()
        if not open_meteo.last_update_success:
            _LOGGER.warning("Entry %s: Open-Meteo not readable yet, its sensors start unavailable", entry_suffix(entry))
    else:
        # Switched off (again): the separate device goes, and its entities with it.
        devices = dr.async_get(hass)
        identifier = open_meteo_identifier(entry)
        for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
            if identifier in device.identifiers:
                devices.async_remove_device(device.id)

    entry.runtime_data = EntryData(forecast=forecast, station=station, precip=precip, pollen=pollen, warnings=warnings, radar=radar, open_meteo=open_meteo, climate=climate)
    await async_serve_frontend(hass)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SwissMeteoConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        async_clear_entry_issues(hass, entry.entry_id)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: SwissMeteoConfigEntry) -> None:
    """The entry is gone: so is what was remembered about its forecast files."""
    await hints_store(hass, entry.entry_id).async_remove()
    await climate_store(hass, entry.entry_id).async_remove()

