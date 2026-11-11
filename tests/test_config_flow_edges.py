"""The corners of the config flow and the options flow: the place search,
lists that cannot be read, and choices that are no longer on offer."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.swiss_meteo.config_flow import SwissMeteoConfigFlow, search_points
from custom_components.swiss_meteo.const import DOMAIN
from custom_components.swiss_meteo.ogd import OgdError, Point

from .test_config_flow import BERN, POINTS, SAENTIS, ZURICH, fake_lists  # noqa: F401  (fixture)

FLOW = "custom_components.swiss_meteo.config_flow."
BERN_LAENGGASSE = Point(point_type=2, point_id=301200, name="Bern", postal_code="3012", station_abbr="BER", height=560.0, lat=46.9550, lon=7.4330)
SWITCHES = {"hourly": True, "extended": False, "warnings": True, "radar": True}
OPTIONS = {**SWITCHES, "gust_threshold": 70, "open_meteo": False}


def entry_at_zurich(hass: HomeAssistant, **data) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="2-800100",
        title="8001 Zürich",
        data={"point_type": 2, "point_id": 800100, "point_name": "Zürich", "point_lat": 47.3769, "point_lon": 8.5417,
              "point_height": 408.0, "station": "SMA", "station_name": "Zürich / Fluntern", "pollen_station": "PZH",
              "pollen_station_name": "Zürich", **SWITCHES, **data},
    )
    entry.add_to_hass(hass)
    return entry


def defaults(result) -> dict:
    """What a form has pre-selected."""
    return {str(key): key.default() for key in result["data_schema"].schema}


def offered(result, field: str) -> list[str]:
    """The values a select field of a form offers, in their order."""
    selector = next(value for key, value in result["data_schema"].schema.items() if str(key) == field)
    return [option["value"] for option in selector.config["options"]]


# --- the place search --------------------------------------------------------


def test_search_by_name() -> None:
    assert search_points(POINTS, "   ") == []
    assert search_points(POINTS, "zür") == [ZURICH]
    assert search_points(POINTS, "ÄNTIS") == [SAENTIS]  # inside the name
    assert search_points(POINTS, "Atlantis") == []
    # names starting with the text come before names containing it
    places = [Point(2, 1, "Oberbern", "3099", "BER", 500.0, 46.9, 7.4), BERN]
    assert search_points(places, "bern") == [BERN, places[0]]


def test_search_by_postal_code() -> None:
    points = [*POINTS, BERN_LAENGGASSE]
    assert search_points(points, "30") == [BERN, BERN_LAENGGASSE]
    assert search_points(points, "3012 bern") == [BERN_LAENGGASSE]
    assert search_points(points, "3012 Zürich") == []
    # a postal code that has no forecast point of its own: the nearest of the area
    assert search_points(points, "3000") == [BERN, BERN_LAENGGASSE]
    assert search_points(points, "3020 Bern") == [BERN_LAENGGASSE, BERN]
    assert search_points(points, "3000 Zürich") == []
    assert search_points(points, "99") == []
    assert search_points(points, "9999") == []


# --- lists that cannot be read -----------------------------------------------


async def test_setup_without_the_lists(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    submitted = {"location": {"latitude": 47.37, "longitude": 8.54}, "search": "", **SWITCHES}
    with patch(FLOW + "async_fetch_points", side_effect=OgdError("HTTP 503")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], submitted)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}

    # the same form again once the lists are back
    result = await hass.config_entries.flow.async_configure(result["flow_id"], submitted)
    assert result["step_id"] == "place"
    assert result["errors"] is None


async def test_reconfigure_without_the_lists(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    entry = entry_at_zurich(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    with patch(FLOW + "async_fetch_stations", side_effect=OgdError("HTTP 503")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"location": {"latitude": 46.948, "longitude": 7.447}, "search": ""}
        )
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data["point_id"] == 800100


# --- reconfigure -------------------------------------------------------------


async def test_reconfigure_starts_from_the_current_choices(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    entry = entry_at_zurich(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    # looked at from Bern, the nearest would be Bern's point and stations
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"location": {"latitude": 46.948, "longitude": 7.447}, "search": ""}
    )
    assert offered(result, "point")[0] == "2:301100"
    assert defaults(result) == {"point": "2:800100", "station": "SMA", "pollen_station": "PZH"}

    # same point, another station: nothing to compare with other entries
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"point": "2:800100", "station": "BER", "pollen_station": "none"}
    )
    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "reconfigure_successful")
    assert (entry.unique_id, entry.title) == ("2-800100", "8001 Zürich")
    assert (entry.data["station"], entry.data["station_name"]) == ("BER", "Bern / Zollikofen")
    assert (entry.data["pollen_station"], entry.data["pollen_station_name"]) == ("", "")


async def test_reconfigure_with_choices_no_longer_on_offer(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    entry = entry_at_zurich(hass, point_id=800900, station="OLD", pollen_station="POL")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"location": {"latitude": 47.3769, "longitude": 8.5417}, "search": ""}
    )
    assert result["step_id"] == "reconfigure_place"
    assert defaults(result) == {"point": "2:800100", "station": "SMA", "pollen_station": "PZH"}


async def test_reconfigure_without_stations_starts_from_none(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    entry = entry_at_zurich(hass, station="", pollen_station="")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"location": {"latitude": 47.3769, "longitude": 8.5417}, "search": ""}
    )
    assert defaults(result) == {"point": "2:800100", "station": "none", "pollen_station": "none"}
    # a new entry has no choice yet
    assert SwissMeteoConfigFlow()._current("station") == "none"


# --- options -----------------------------------------------------------------


async def test_options_form(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    entry = entry_at_zurich(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {}
    assert offered(result, "station") == ["SMA", "BER", "none"]
    assert offered(result, "pollen_station") == ["PZH", "PBE", "none"]
    assert defaults(result) == {**SWITCHES, "gust_threshold": 60.0, "station": "SMA", "pollen_station": "PZH", "open_meteo": False}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**OPTIONS, "hourly": False, "gust_threshold": 55, "station": "BER", "pollen_station": "PBE", "open_meteo": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        "hourly": False, "extended": False, "warnings": True, "radar": True, "open_meteo": True, "gust_threshold": 55.0,
        "station": "BER", "station_name": "Bern / Zollikofen", "pollen_station": "PBE", "pollen_station_name": "Bern",
    }


async def test_options_without_stations(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    entry = entry_at_zurich(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**OPTIONS, "station": "none", "pollen_station": "none"}
    )
    chosen = result["data"]
    assert (chosen["station"], chosen["station_name"], chosen["pollen_station"], chosen["pollen_station_name"]) == ("", "", "", "")


async def test_options_keep_a_station_that_left_the_lists(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    entry = entry_at_zurich(hass, station="OLD", pollen_station="POL")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert offered(result, "station") == ["OLD", "SMA", "BER", "none"]
    assert offered(result, "pollen_station") == ["POL", "PZH", "PBE", "none"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**OPTIONS, "station": "OLD", "pollen_station": "POL"}
    )
    # no name to be found: the abbreviation stands in
    assert (result["data"]["station_name"], result["data"]["pollen_station_name"]) == ("OLD", "POL")


async def test_options_without_the_lists(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    entry = entry_at_zurich(hass)
    down = OgdError("HTTP 503")
    with patch(FLOW + "async_fetch_stations", side_effect=down), patch(FLOW + "async_fetch_pollen_stations", side_effect=down):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["errors"] == {"base": "cannot_connect"}
        # the current choices can be kept, nothing else is known
        assert offered(result, "station") == ["SMA", "none"]
        assert offered(result, "pollen_station") == ["PZH", "none"]

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**OPTIONS, "station": "SMA", "pollen_station": "PZH"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert (result["data"]["station_name"], result["data"]["pollen_station_name"]) == ("SMA", "PZH")
