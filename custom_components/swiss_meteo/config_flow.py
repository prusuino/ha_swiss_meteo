"""Config flow: a location (the instance's by default), then the forecast
point and the weather station nearest to it, pre-selected. The same two
options (hourly forecast, extended values) and the station can be changed
later in the Configure dialog."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_EXTENDED,
    CONF_HOURLY,
    CONF_POINT_HEIGHT,
    CONF_POINT_ID,
    CONF_POINT_LAT,
    CONF_POINT_LON,
    CONF_POINT_NAME,
    CONF_POINT_TYPE,
    CONF_STATION,
    CONF_STATION_NAME,
    DOMAIN,
    POINT_TYPE_MOUNTAIN,
    POINT_TYPE_POSTAL,
    POINT_TYPE_STATION,
)
from .ogd import OgdError, Point, Station, async_fetch_points, async_fetch_stations, nearest

_LOGGER = logging.getLogger(__name__)

CONF_LOCATION = "location"
CONF_POINT = "point"
NO_STATION = "none"
_NEAREST_POINTS = 5
_NEAREST_STATIONS = 4


def _point_label(distance: float, point: Point) -> str:
    kind = {POINT_TYPE_STATION: "station", POINT_TYPE_POSTAL: "", POINT_TYPE_MOUNTAIN: "mountain"}.get(point.point_type, "")
    name = f"{point.postal_code} {point.name}" if point.postal_code else point.name
    height = f", {point.height:.0f} m" if point.height is not None else ""
    kind_text = f" ({kind})" if kind else ""
    return f"{name}{kind_text}{height} – {distance:.1f} km"


def _station_label(distance: float, station: Station) -> str:
    height = f", {station.height:.0f} m" if station.height is not None else ""
    return f"{station.name} {station.canton} ({station.abbr}{height}) – {distance:.1f} km"


def _point_value(point: Point) -> str:
    return f"{point.point_type}:{point.point_id}"


class SwissMeteoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._lat: float | None = None
        self._lon: float | None = None
        self._points: list[tuple[float, Point]] = []
        self._stations: list[tuple[float, Station]] = []
        self._hourly = True
        self._extended = False

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            loc = user_input[CONF_LOCATION]
            self._lat, self._lon = float(loc["latitude"]), float(loc["longitude"])
            self._hourly = bool(user_input.get(CONF_HOURLY, True))
            self._extended = bool(user_input.get(CONF_EXTENDED, False))
            session = async_get_clientsession(self.hass)
            try:
                points = await async_fetch_points(session)
                stations = await async_fetch_stations(session)
            except OgdError as err:
                _LOGGER.debug("Point lists not readable: %s", err)
                errors["base"] = "cannot_connect"
            else:
                self._points = nearest(points, self._lat, self._lon, _NEAREST_POINTS)
                self._stations = nearest(stations, self._lat, self._lon, _NEAREST_STATIONS)
                return await self.async_step_place()
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LOCATION,
                    default={"latitude": self.hass.config.latitude, "longitude": self.hass.config.longitude},
                ): selector.LocationSelector(),
                vol.Required(CONF_HOURLY, default=True): selector.BooleanSelector(),
                vol.Required(CONF_EXTENDED, default=False): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_place(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            chosen = user_input[CONF_POINT]
            point = next(p for _d, p in self._points if _point_value(p) == chosen)
            station_abbr = user_input.get(CONF_STATION, NO_STATION)
            station = next((s for _d, s in self._stations if s.abbr == station_abbr), None)
            await self.async_set_unique_id(f"{point.point_type}-{point.point_id}")
            self._abort_if_unique_id_configured()
            title = f"{point.postal_code} {point.name}".strip() if point.postal_code else point.name
            return self.async_create_entry(
                title=title,
                data={
                    CONF_POINT_TYPE: point.point_type,
                    CONF_POINT_ID: point.point_id,
                    CONF_POINT_NAME: point.name,
                    CONF_POINT_LAT: point.lat,
                    CONF_POINT_LON: point.lon,
                    CONF_POINT_HEIGHT: point.height,
                    CONF_STATION: station.abbr if station else "",
                    CONF_STATION_NAME: station.name if station else "",
                    CONF_HOURLY: self._hourly,
                    CONF_EXTENDED: self._extended,
                },
            )
        point_options = [
            selector.SelectOptionDict(value=_point_value(p), label=_point_label(d, p)) for d, p in self._points
        ]
        station_options = [
            selector.SelectOptionDict(value=s.abbr, label=_station_label(d, s)) for d, s in self._stations
        ]
        station_options.append(selector.SelectOptionDict(value=NO_STATION, label="–"))
        schema = vol.Schema(
            {
                vol.Required(CONF_POINT, default=point_options[0]["value"]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=point_options, mode=selector.SelectSelectorMode.LIST)
                ),
                vol.Required(CONF_STATION, default=station_options[0]["value"]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=station_options, mode=selector.SelectSelectorMode.LIST)
                ),
            }
        )
        return self.async_show_form(step_id="place", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SwissMeteoOptionsFlow:
        return SwissMeteoOptionsFlow()


class SwissMeteoOptionsFlow(OptionsFlow):
    """Hourly forecast on/off, extended values on/off, another station."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            station_abbr = user_input.get(CONF_STATION, NO_STATION)
            station_name = ""
            if station_abbr != NO_STATION:
                try:
                    stations = await async_fetch_stations(async_get_clientsession(self.hass))
                    station_name = next((s.name for s in stations if s.abbr == station_abbr), station_abbr)
                except OgdError:
                    station_name = station_abbr
            options = {
                CONF_HOURLY: bool(user_input.get(CONF_HOURLY, True)),
                CONF_EXTENDED: bool(user_input.get(CONF_EXTENDED, False)),
                CONF_STATION: "" if station_abbr == NO_STATION else station_abbr,
                CONF_STATION_NAME: station_name,
            }
            return self.async_create_entry(title="", data=options)

        current_station = entry.options.get(CONF_STATION, entry.data.get(CONF_STATION, "")) or NO_STATION
        station_options = [selector.SelectOptionDict(value=NO_STATION, label="–")]
        try:
            stations = await async_fetch_stations(async_get_clientsession(self.hass))
            lat = float(entry.data.get(CONF_POINT_LAT, self.hass.config.latitude))
            lon = float(entry.data.get(CONF_POINT_LON, self.hass.config.longitude))
            station_options = [
                selector.SelectOptionDict(value=s.abbr, label=_station_label(d, s)) for d, s in nearest(stations, lat, lon, 8)
            ] + station_options
            if current_station != NO_STATION and all(o["value"] != current_station for o in station_options):
                station_options.insert(0, selector.SelectOptionDict(value=current_station, label=current_station))
        except OgdError:
            errors["base"] = "cannot_connect"
            if current_station != NO_STATION:
                station_options.insert(0, selector.SelectOptionDict(value=current_station, label=current_station))
        schema = vol.Schema(
            {
                vol.Required(CONF_HOURLY, default=entry.options.get(CONF_HOURLY, entry.data.get(CONF_HOURLY, True))): selector.BooleanSelector(),
                vol.Required(CONF_EXTENDED, default=entry.options.get(CONF_EXTENDED, entry.data.get(CONF_EXTENDED, False))): selector.BooleanSelector(),
                vol.Required(CONF_STATION, default=current_station): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=station_options, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
