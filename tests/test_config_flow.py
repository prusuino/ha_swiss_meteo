"""Config flow tests: setup by location and by search, duplicate detection
and the reconfigure flow. The MeteoSwiss lists are faked, nothing is
fetched."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_component

from custom_components.swiss_meteo.const import (
    CONF_POINT_ID,
    CONF_POINT_NAME,
    CONF_POINT_TYPE,
    CONF_POLLEN_STATION,
    CONF_STATION,
    DOMAIN,
)
from custom_components.swiss_meteo.ogd import Point, Station
from custom_components.swiss_meteo.pollen import PollenStation

ZURICH = Point(point_type=2, point_id=800100, name="Zürich", postal_code="8001", station_abbr="SMA", height=408.0, lat=47.3769, lon=8.5417)
BERN = Point(point_type=2, point_id=301100, name="Bern", postal_code="3011", station_abbr="BER", height=542.0, lat=46.9480, lon=7.4474)
SAENTIS = Point(point_type=3, point_id=90001, name="Säntis", postal_code="", station_abbr="SAE", height=2502.0, lat=47.2494, lon=9.3433)
POINTS = [ZURICH, BERN, SAENTIS]
STATIONS = [
    Station("SMA", "Zürich / Fluntern", "ZH", 556.0, 47.3781, 8.5658),
    Station("BER", "Bern / Zollikofen", "BE", 553.0, 46.9908, 7.4641),
]
POLLEN = [PollenStation("PZH", "Zürich", "ZH", 556.0, 47.3781, 8.5658), PollenStation("PBE", "Bern", "BE", 553.0, 46.9908, 7.4641)]


@pytest.fixture
def fake_lists(hass: HomeAssistant):
    """Serve the forecast points, stations and pollen stations from memory.

    The integration depends on the recorder (for the station history import);
    the flow does not use it, so the recorder is marked as set up instead of
    being started."""
    mock_component(hass, "recorder")
    with (
        patch("custom_components.swiss_meteo.config_flow.async_fetch_points", return_value=POINTS),
        patch("custom_components.swiss_meteo.config_flow.async_fetch_stations", return_value=STATIONS),
        patch("custom_components.swiss_meteo.config_flow.async_fetch_pollen_stations", return_value=POLLEN),
    ):
        yield


async def test_setup_by_location(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    """Home location, nearest point and station pre-selected, entry created."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"location": {"latitude": 47.37, "longitude": 8.54}, "search": "", "hourly": True, "extended": False, "warnings": True, "radar": False},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "place"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"point": "2:800100", "station": "SMA", "pollen_station": "none"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "8001 Zürich"
    assert result["data"][CONF_POINT_ID] == 800100
    assert result["data"][CONF_POINT_TYPE] == 2
    assert result["data"][CONF_STATION] == "SMA"
    assert result["data"][CONF_POLLEN_STATION] == ""
    assert result["data"]["radar"] is False
    assert result["result"].unique_id == "2-800100"


async def test_setup_by_search_and_duplicate(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    """A postal-code search lists the matches; the same point twice is refused."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"location": {"latitude": 47.0, "longitude": 8.0}, "search": "3011 Bern", "hourly": True, "extended": False, "warnings": True, "radar": True},
    )
    assert result["step_id"] == "search"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"point": "2:301100"})
    assert result["step_id"] == "place"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"point": "2:301100", "station": "BER", "pollen_station": "PBE"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "3011 Bern"
    assert result["data"][CONF_POLLEN_STATION] == "PBE"

    # the same forecast point again
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"location": {"latitude": 46.95, "longitude": 7.45}, "search": "", "hourly": False, "extended": False, "warnings": False, "radar": False},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"point": "2:301100", "station": "none", "pollen_station": "none"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_search_without_match_shows_error(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"location": {"latitude": 47.0, "longitude": 8.0}, "search": "Atlantis", "hourly": True, "extended": False, "warnings": True, "radar": True},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"search": "no_match"}


async def test_reconfigure_moves_the_entry(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    """Reconfigure keeps the entry, changes point, title and unique id, and
    drops the station choice from the options so the data counts again."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="2-800100",
        title="8001 Zürich",
        data={CONF_POINT_TYPE: 2, CONF_POINT_ID: 800100, CONF_POINT_NAME: "Zürich", "point_lat": 47.3769, "point_lon": 8.5417,
              "point_height": 408.0, CONF_STATION: "SMA", "station_name": "Zürich / Fluntern", CONF_POLLEN_STATION: "",
              "pollen_station_name": "", "hourly": True, "extended": False, "warnings": True, "radar": True},
        options={CONF_STATION: "SMA", "station_name": "Zürich / Fluntern", "gust_threshold": 70.0},
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"location": {"latitude": 47.3769, "longitude": 8.5417}, "search": "Bern"}
    )
    assert result["step_id"] == "reconfigure_search"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"point": "2:301100"})
    assert result["step_id"] == "reconfigure_place"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"point": "2:301100", "station": "BER", "pollen_station": "none"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"

    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert entry.title == "3011 Bern"
    assert entry.unique_id == "2-301100"
    assert entry.data[CONF_POINT_ID] == 301100
    assert entry.data[CONF_STATION] == "BER"
    assert entry.data["hourly"] is True  # the switches are untouched
    assert CONF_STATION not in entry.options
    assert entry.options["gust_threshold"] == 70.0


async def test_reconfigure_refuses_another_entrys_point(hass: HomeAssistant, enable_custom_integrations, fake_lists) -> None:
    for point in (ZURICH, BERN):
        MockConfigEntry(
            domain=DOMAIN, unique_id=f"2-{point.point_id}", title=point.name,
            data={CONF_POINT_TYPE: 2, CONF_POINT_ID: point.point_id, "point_lat": point.lat, "point_lon": point.lon},
        ).add_to_hass(hass)
    zurich_entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": zurich_entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"location": {"latitude": 46.948, "longitude": 7.447}, "search": ""}
    )
    assert result["step_id"] == "reconfigure_place"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"point": "2:301100", "station": "none", "pollen_station": "none"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
