"""Config flow: a location (the instance's by default) or a place / postal
code search, then the forecast point, the weather station and the pollen
station nearest to it, pre-selected. The options (hourly forecast,
extended values, official warnings, radar, gust threshold) and the stations
can be changed later in the Configure dialog; Reconfigure (the entry's
menu) moves the entry to another place with the same two steps as the
setup, keeping its entities, their ids and history."""
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
    CONF_GUST_THRESHOLD,
    CONF_HOURLY,
    CONF_POINT_HEIGHT,
    CONF_POINT_ID,
    CONF_POINT_LAT,
    CONF_POINT_LON,
    CONF_POINT_NAME,
    CONF_POINT_TYPE,
    CONF_POLLEN_STATION,
    CONF_POLLEN_STATION_NAME,
    CONF_RADAR,
    CONF_STATION,
    CONF_STATION_NAME,
    CONF_WARNINGS,
    DEFAULT_GUST_THRESHOLD,
    DOMAIN,
    POINT_TYPE_MOUNTAIN,
    POINT_TYPE_POSTAL,
    POINT_TYPE_STATION,
)
from .ogd import OgdError, Point, Station, async_fetch_points, async_fetch_stations, nearest
from .pollen import PollenStation, async_fetch_pollen_stations

_LOGGER = logging.getLogger(__name__)

CONF_LOCATION = "location"
CONF_SEARCH = "search"
CONF_POINT = "point"
_MAX_MATCHES = 12
NO_STATION = "none"
_NEAREST_POINTS = 5
_NEAREST_STATIONS = 4
_NEAREST_POLLEN = 3

# Station choices live in the options once Configure was used; a reconfigure
# writes the new choice to the data and drops these so the data counts again.
_STATION_KEYS = (CONF_STATION, CONF_STATION_NAME, CONF_POLLEN_STATION, CONF_POLLEN_STATION_NAME)


def _point_label(distance: float, point: Point) -> str:
    kind = {POINT_TYPE_STATION: "station", POINT_TYPE_POSTAL: "", POINT_TYPE_MOUNTAIN: "mountain"}.get(point.point_type, "")
    name = f"{point.postal_code} {point.name}" if point.postal_code else point.name
    height = f", {point.height:.0f} m" if point.height is not None else ""
    kind_text = f" ({kind})" if kind else ""
    return f"{name}{kind_text}{height} – {distance:.1f} km"


def _station_label(distance: float, station: Station) -> str:
    height = f", {station.height:.0f} m" if station.height is not None else ""
    return f"{station.name} {station.canton} ({station.abbr}{height}) – {distance:.1f} km"


def _pollen_label(distance: float, station: PollenStation) -> str:
    height = f", {station.height:.0f} m" if station.height is not None else ""
    return f"{station.name} {station.canton} ({station.abbr}{height}) – {distance:.1f} km"


def _point_value(point: Point) -> str:
    return f"{point.point_type}:{point.point_id}"


def _point_title(point: Point) -> str:
    return f"{point.postal_code} {point.name}".strip() if point.postal_code else point.name


def search_points(points: list[Point], text: str) -> list[Point]:
    """The points whose postal code or name matches the text: postal code
    prefix first, then names starting with the text, then names containing
    it. The text may also be '8001 Zürich' style; the postal code alone
    decides then."""
    q = " ".join(text.split()).lower()
    if not q:
        return []
    first = q.split(" ", 1)[0]
    plz = first if first.isdigit() else ""
    name_q = q[len(first):].strip() if plz else q
    tiers: tuple[list[Point], list[Point], list[Point]] = ([], [], [])
    for p in points:
        name = (p.name or "").lower()
        code = str(p.postal_code or "")
        if plz:
            if code.startswith(plz) and (not name_q or name_q in name):
                tiers[0].append(p)
            continue
        if name.startswith(q):
            tiers[1].append(p)
        elif q in name:
            tiers[2].append(p)
    # places (postal-code centres) before stations and mountain points within each tier
    out = [p for tier in tiers for p in sorted(tier, key=lambda p: (p.point_type != POINT_TYPE_POSTAL, str(p.postal_code or ""), p.name or ""))]
    if plz and not out and len(plz) >= 3:
        # no such postal code in the list (3000 Bern has only its delivery
        # districts 3004…): offer the numerically nearest codes of the area
        target = int(plz.ljust(4, "0")[:4])
        near = [p for p in points if str(p.postal_code or "").isdigit() and str(p.postal_code)[:2] == plz[:2] and (not name_q or name_q in (p.name or "").lower())]
        near.sort(key=lambda p: (abs(int(p.postal_code) - target), p.name or ""))
        out = near
    return out[:_MAX_MATCHES]


class SwissMeteoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._lat: float | None = None
        self._lon: float | None = None
        self._points: list[tuple[float, Point]] = []
        self._stations: list[tuple[float, Station]] = []
        self._pollen: list[tuple[float, PollenStation]] = []
        self._hourly = True
        self._extended = False
        self._warnings = True
        self._radar = True
        self._all_points: list[Point] = []
        self._all_stations: list[Station] = []
        self._all_pollen: list[PollenStation] = []
        self._matches: list[Point] = []
        # The entry being reconfigured; None while setting up a new one.
        self._entry: ConfigEntry | None = None

    # ------------------------------------------------------------ shared

    async def _async_location_submitted(
        self, user_input: dict[str, Any], search_step: str, place_step: str
    ) -> tuple[ConfigFlowResult | None, dict[str, str]]:
        """Handle the location form of setup and reconfigure: read the
        lists, then go to the search results or straight to the places
        around the location. Returns the next step's result, or None with
        the form errors to show. (A flow result is itself a dict, so the
        two are told apart by position, not by type.)"""
        errors: dict[str, str] = {}
        loc = user_input[CONF_LOCATION]
        self._lat, self._lon = float(loc["latitude"]), float(loc["longitude"])
        search = str(user_input.get(CONF_SEARCH) or "").strip()
        session = async_get_clientsession(self.hass)
        try:
            points = await async_fetch_points(session)
            stations = await async_fetch_stations(session)
            pollen = await async_fetch_pollen_stations(session)
        except OgdError as err:
            _LOGGER.debug("Point lists not readable: %s", err)
            errors["base"] = "cannot_connect"
            return None, errors
        self._all_points = points
        self._all_stations = stations
        self._all_pollen = pollen
        if search:
            self._matches = search_points(points, search)
            if not self._matches:
                errors[CONF_SEARCH] = "no_match"
                return None, errors
            return await getattr(self, f"async_step_{search_step}")(), errors
        self._pick_around(self._lat, self._lon)
        return await getattr(self, f"async_step_{place_step}")(), errors

    def _pick_around(self, lat: float, lon: float, chosen: Point | None = None) -> None:
        """The nearest forecast points, stations and pollen stations around
        a location; a chosen point (from the search) goes first."""
        points = nearest(self._all_points, lat, lon, _NEAREST_POINTS)
        if chosen is not None:
            others = [(d, p) for d, p in points if _point_value(p) != _point_value(chosen)]
            points = [(0.0, chosen)] + others[: _NEAREST_POINTS - 1]
        self._points = points
        self._stations = nearest(self._all_stations, lat, lon, _NEAREST_STATIONS)
        self._pollen = nearest(self._all_pollen, lat, lon, _NEAREST_POLLEN)

    def _location_schema(self, lat: float, lon: float, with_options: bool) -> vol.Schema:
        fields: dict[Any, Any] = {
            vol.Required(CONF_LOCATION, default={"latitude": lat, "longitude": lon}): selector.LocationSelector(),
            vol.Optional(CONF_SEARCH, default=""): selector.TextSelector(),
        }
        if with_options:
            fields.update(
                {
                    vol.Required(CONF_HOURLY, default=True): selector.BooleanSelector(),
                    vol.Required(CONF_EXTENDED, default=False): selector.BooleanSelector(),
                    vol.Required(CONF_WARNINGS, default=True): selector.BooleanSelector(),
                    vol.Required(CONF_RADAR, default=True): selector.BooleanSelector(),
                }
            )
        return vol.Schema(fields)

    async def _async_search_form(
        self, step_id: str, user_input: dict[str, Any] | None, place_step: str
    ) -> ConfigFlowResult:
        """The places matching the search text; the chosen one becomes the
        location, and the stations are picked around it."""
        if user_input is not None:
            chosen = user_input[CONF_POINT]
            point = next(p for p in self._matches if _point_value(p) == chosen)
            self._lat, self._lon = point.lat, point.lon
            self._pick_around(self._lat, self._lon, point)
            return await getattr(self, f"async_step_{place_step}")()
        options = [selector.SelectOptionDict(value=_point_value(p), label=_point_label(0.0, p).rsplit(" – ", 1)[0]) for p in self._matches]
        schema = vol.Schema(
            {
                vol.Required(CONF_POINT, default=options[0]["value"]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.LIST)
                ),
            }
        )
        return self.async_show_form(step_id=step_id, data_schema=schema)

    def _current(self, key: str) -> str:
        """The current station choice of the entry being reconfigured
        (options win over data), NO_STATION when there is none."""
        if self._entry is None:
            return NO_STATION
        return str(self._entry.options.get(key, self._entry.data.get(key, "")) or "") or NO_STATION

    async def _async_place_form(self, step_id: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        if user_input is not None:
            chosen = user_input[CONF_POINT]
            point = next(p for _d, p in self._points if _point_value(p) == chosen)
            station_abbr = user_input.get(CONF_STATION, NO_STATION)
            station = next((s for _d, s in self._stations if s.abbr == station_abbr), None)
            pollen_abbr = user_input.get(CONF_POLLEN_STATION, NO_STATION)
            pollen = next((p for _d, p in self._pollen if p.abbr == pollen_abbr), None)
            return await self._async_finish(point, station, pollen)

        point_options = [
            selector.SelectOptionDict(value=_point_value(p), label=_point_label(d, p)) for d, p in self._points
        ]
        station_options = [
            selector.SelectOptionDict(value=s.abbr, label=_station_label(d, s)) for d, s in self._stations
        ]
        station_options.append(selector.SelectOptionDict(value=NO_STATION, label="–"))
        pollen_options = [
            selector.SelectOptionDict(value=p.abbr, label=_pollen_label(d, p)) for d, p in self._pollen
        ]
        pollen_options.append(selector.SelectOptionDict(value=NO_STATION, label="–"))

        # Setup: nearest first. Reconfigure: the entry's current choices when
        # they are among the offered ones, otherwise nearest as well.
        point_default = point_options[0]["value"]
        station_default = station_options[0]["value"]
        pollen_default = pollen_options[0]["value"]
        if self._entry is not None:
            data = self._entry.data
            current_point = f"{data.get(CONF_POINT_TYPE)}:{data.get(CONF_POINT_ID)}"
            if any(o["value"] == current_point for o in point_options):
                point_default = current_point
            current_station = self._current(CONF_STATION)
            if any(o["value"] == current_station for o in station_options):
                station_default = current_station
            current_pollen = self._current(CONF_POLLEN_STATION)
            if any(o["value"] == current_pollen for o in pollen_options):
                pollen_default = current_pollen
        schema = vol.Schema(
            {
                vol.Required(CONF_POINT, default=point_default): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=point_options, mode=selector.SelectSelectorMode.LIST)
                ),
                vol.Required(CONF_STATION, default=station_default): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=station_options, mode=selector.SelectSelectorMode.LIST)
                ),
                vol.Required(CONF_POLLEN_STATION, default=pollen_default): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=pollen_options, mode=selector.SelectSelectorMode.LIST)
                ),
            }
        )
        return self.async_show_form(step_id=step_id, data_schema=schema)

    async def _async_finish(
        self, point: Point, station: Station | None, pollen: PollenStation | None
    ) -> ConfigFlowResult:
        """Create the entry, or update the one being reconfigured."""
        unique_id = f"{point.point_type}-{point.point_id}"
        await self.async_set_unique_id(unique_id)
        place = {
            CONF_POINT_TYPE: point.point_type,
            CONF_POINT_ID: point.point_id,
            CONF_POINT_NAME: point.name,
            CONF_POINT_LAT: point.lat,
            CONF_POINT_LON: point.lon,
            CONF_POINT_HEIGHT: point.height,
            CONF_STATION: station.abbr if station else "",
            CONF_STATION_NAME: station.name if station else "",
            CONF_POLLEN_STATION: pollen.abbr if pollen else "",
            CONF_POLLEN_STATION_NAME: pollen.name if pollen else "",
        }
        if self._entry is None:
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_point_title(point),
                data={
                    **place,
                    CONF_HOURLY: self._hourly,
                    CONF_EXTENDED: self._extended,
                    CONF_WARNINGS: self._warnings,
                    CONF_RADAR: self._radar,
                },
            )
        if unique_id != self._entry.unique_id:
            self._abort_if_unique_id_configured()
        # Update only: the entry's update listener reloads it on a change
        # (Home Assistant asks integrations with a listener to do it that way).
        self.hass.config_entries.async_update_entry(
            self._entry,
            unique_id=unique_id,
            title=_point_title(point),
            data={**self._entry.data, **place},
            options={k: v for k, v in self._entry.options.items() if k not in _STATION_KEYS},
        )
        return self.async_abort(reason="reconfigure_successful")

    # ------------------------------------------------------------- setup

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._hourly = bool(user_input.get(CONF_HOURLY, True))
            self._extended = bool(user_input.get(CONF_EXTENDED, False))
            self._warnings = bool(user_input.get(CONF_WARNINGS, True))
            self._radar = bool(user_input.get(CONF_RADAR, True))
            result, errors = await self._async_location_submitted(user_input, "search", "place")
            if result is not None:
                return result
        schema = self._location_schema(self.hass.config.latitude, self.hass.config.longitude, with_options=True)
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_search(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_search_form("search", user_input, "place")

    async def async_step_place(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_place_form("place", user_input)

    # ------------------------------------------------------- reconfigure

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Move the entry to another place: location or search, then the
        point and stations around it. The hourly/extended/warnings/radar
        switches stay as set in Configure."""
        self._entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            result, errors = await self._async_location_submitted(user_input, "reconfigure_search", "reconfigure_place")
            if result is not None:
                return result
        lat = float(self._entry.data.get(CONF_POINT_LAT, self.hass.config.latitude))
        lon = float(self._entry.data.get(CONF_POINT_LON, self.hass.config.longitude))
        schema = self._location_schema(lat, lon, with_options=False)
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    async def async_step_reconfigure_search(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_search_form("reconfigure_search", user_input, "reconfigure_place")

    async def async_step_reconfigure_place(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_place_form("reconfigure_place", user_input)

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
            pollen_abbr = user_input.get(CONF_POLLEN_STATION, NO_STATION)
            pollen_name = ""
            if pollen_abbr != NO_STATION:
                try:
                    pollen_stations = await async_fetch_pollen_stations(async_get_clientsession(self.hass))
                    pollen_name = next((p.name for p in pollen_stations if p.abbr == pollen_abbr), pollen_abbr)
                except OgdError:
                    pollen_name = pollen_abbr
            options = {
                CONF_HOURLY: bool(user_input.get(CONF_HOURLY, True)),
                CONF_EXTENDED: bool(user_input.get(CONF_EXTENDED, False)),
                CONF_WARNINGS: bool(user_input.get(CONF_WARNINGS, True)),
                CONF_RADAR: bool(user_input.get(CONF_RADAR, True)),
                CONF_GUST_THRESHOLD: float(user_input.get(CONF_GUST_THRESHOLD, DEFAULT_GUST_THRESHOLD)),
                CONF_STATION: "" if station_abbr == NO_STATION else station_abbr,
                CONF_STATION_NAME: station_name,
                CONF_POLLEN_STATION: "" if pollen_abbr == NO_STATION else pollen_abbr,
                CONF_POLLEN_STATION_NAME: pollen_name,
            }
            return self.async_create_entry(title="", data=options)

        current_station = entry.options.get(CONF_STATION, entry.data.get(CONF_STATION, "")) or NO_STATION
        current_pollen = entry.options.get(CONF_POLLEN_STATION, entry.data.get(CONF_POLLEN_STATION, "")) or NO_STATION
        station_options = [selector.SelectOptionDict(value=NO_STATION, label="–")]
        pollen_options = [selector.SelectOptionDict(value=NO_STATION, label="–")]
        lat = float(entry.data.get(CONF_POINT_LAT, self.hass.config.latitude))
        lon = float(entry.data.get(CONF_POINT_LON, self.hass.config.longitude))
        try:
            session = async_get_clientsession(self.hass)
            stations = await async_fetch_stations(session)
            station_options = [
                selector.SelectOptionDict(value=s.abbr, label=_station_label(d, s)) for d, s in nearest(stations, lat, lon, 8)
            ] + station_options
            pollen_stations = await async_fetch_pollen_stations(session)
            pollen_options = [
                selector.SelectOptionDict(value=p.abbr, label=_pollen_label(d, p)) for d, p in nearest(pollen_stations, lat, lon, len(pollen_stations))
            ] + pollen_options
        except OgdError:
            errors["base"] = "cannot_connect"
        if current_station != NO_STATION and all(o["value"] != current_station for o in station_options):
            station_options.insert(0, selector.SelectOptionDict(value=current_station, label=current_station))
        if current_pollen != NO_STATION and all(o["value"] != current_pollen for o in pollen_options):
            pollen_options.insert(0, selector.SelectOptionDict(value=current_pollen, label=current_pollen))
        schema = vol.Schema(
            {
                vol.Required(CONF_HOURLY, default=entry.options.get(CONF_HOURLY, entry.data.get(CONF_HOURLY, True))): selector.BooleanSelector(),
                vol.Required(CONF_EXTENDED, default=entry.options.get(CONF_EXTENDED, entry.data.get(CONF_EXTENDED, False))): selector.BooleanSelector(),
                vol.Required(CONF_WARNINGS, default=entry.options.get(CONF_WARNINGS, entry.data.get(CONF_WARNINGS, True))): selector.BooleanSelector(),
                vol.Required(CONF_RADAR, default=entry.options.get(CONF_RADAR, entry.data.get(CONF_RADAR, True))): selector.BooleanSelector(),
                vol.Required(CONF_GUST_THRESHOLD, default=float(entry.options.get(CONF_GUST_THRESHOLD, entry.data.get(CONF_GUST_THRESHOLD, DEFAULT_GUST_THRESHOLD)))): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=30, max=150, step=5, unit_of_measurement="km/h", mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Required(CONF_STATION, default=current_station): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=station_options, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(CONF_POLLEN_STATION, default=current_pollen): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=pollen_options, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
