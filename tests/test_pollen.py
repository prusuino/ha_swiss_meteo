"""Pollen: the station list, a station's hours of the day, the load
classes, and the coordinator against files served from memory."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.swiss_meteo.const import DOMAIN
from custom_components.swiss_meteo.ogd import OgdError, OgdUnavailable
from custom_components.swiss_meteo.pollen import (
    LEVELS,
    LOAD_CLASSES,
    POLLEN_PARAMS,
    POLLEN_STATIONS_META_URL,
    SPECIES,
    PollenCoordinator,
    async_fetch_pollen_reading,
    async_fetch_pollen_stations,
    level_for,
    pollen_now_url,
)

from .conftest import ENTRY_ID, NOW, make_entry
from .fakes import FakeResponse, FakeSession

SESSION = "custom_components.swiss_meteo.pollen.async_get_clientsession"
ISSUE = f"pollen_unreadable_{ENTRY_ID}"

STATIONS_CSV = (
    "station_abbr;station_name;station_canton;station_height_masl;station_coordinates_wgs84_lat;station_coordinates_wgs84_lon\n"
    "PZH;Zürich;ZH;556;47.378;8.566\n"
    "PBE; Bern ;BE;;46.951;7.439\n"
    "PXX;Nowhere;XX;500;north;7.0\n"
).encode("latin-1")

HEADER = "station_abbr;reference_timestamp;" + ";".join(POLLEN_PARAMS) + "\n"


def day_file(*rows: str) -> bytes:
    """A station's file; a row is "time;birch;grasses" and the other
    species stay empty."""
    return (HEADER + "".join(f"PZH;{row};;;;;\n" for row in rows)).encode("latin-1")


MORNING = day_file(
    "08.11.2026 07:00;10;0",
    "08.11.2026 08:00;20;2",
    "sometime;99;99",
    "08.11.2026 09:00;30;",
    "08.11.2026 10:00;;",
)


def test_load_classes() -> None:
    assert level_for("birch", None) is None
    assert level_for("birch", 0.4) == "none"
    assert level_for("ragweed", 500.0) == "none"  # no class defined for the species
    assert [level_for("birch", value) for value in (1, 10, 11, 69, 70, 299, 300)] == [
        "low", "low", "moderate", "moderate", "high", "high", "very_high",
    ]
    assert [level_for("grasses", value) for value in (19, 20, 49, 50, 149, 150)] == [
        "low", "moderate", "moderate", "high", "high", "very_high",
    ]
    assert set(LOAD_CLASSES) == set(SPECIES)
    assert LEVELS[0] == "none" and LEVELS[-1] == "very_high"


def test_file_of_a_station() -> None:
    assert pollen_now_url("PZH").endswith("/pzh/ogd-pollen_pzh_h_now.csv")


async def test_station_list() -> None:
    session = FakeSession({POLLEN_STATIONS_META_URL: STATIONS_CSV})
    stations = await async_fetch_pollen_stations(session)
    # the row without usable coordinates is left out
    assert [station.abbr for station in stations] == ["PZH", "PBE"]
    zurich, bern = stations
    assert (zurich.name, zurich.canton, zurich.height, zurich.lat, zurich.lon) == ("Zürich", "ZH", 556.0, 47.378, 8.566)
    assert (bern.name, bern.height) == ("Bern", None)


async def test_station_list_without_the_expected_columns() -> None:
    session = FakeSession({POLLEN_STATIONS_META_URL: b"station_abbr;station_name\nPZH;Z\n"})
    assert await async_fetch_pollen_stations(session) == []


async def test_reading_is_the_newest_hour_and_the_mean_of_the_day() -> None:
    reading = await async_fetch_pollen_reading(FakeSession({pollen_now_url("PZH"): MORNING}), "PZH")
    assert reading.abbr == "PZH"
    # the last hour is still empty and the row without a time is skipped
    assert reading.timestamp == datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
    assert reading.current == {"birch": 30.0, "grasses": 2.0}
    assert reading.daily_mean == {"birch": 20.0, "grasses": 1.0}
    assert reading.hours == 3


@pytest.mark.parametrize("body", [HEADER.encode(), day_file("08.11.2026 07:00;;"), b"station_abbr;kabetuh0\nPZH;5\n"])
async def test_reading_without_values(body: bytes) -> None:
    with pytest.raises(OgdError, match="pollen file of PZH has no values"):
        await async_fetch_pollen_reading(FakeSession({pollen_now_url("PZH"): body}), "PZH")


async def test_reading_of_a_file_that_is_not_there() -> None:
    with pytest.raises(OgdUnavailable, match="HTTP 404"):
        await async_fetch_pollen_reading(FakeSession(), "PZH")


# --- coordinator -------------------------------------------------------------


async def test_station_comes_from_the_options_first(hass: HomeAssistant, swiss_now) -> None:
    entry = make_entry(hass, {"pollen_station": "PZH"}, {"pollen_station": "PBE"})
    assert PollenCoordinator(hass, entry).station == "PBE"


async def test_levels_of_the_day(hass: HomeAssistant, swiss_now, freezer) -> None:
    coordinator = PollenCoordinator(hass, make_entry(hass, {"pollen_station": "PZH"}))
    assert coordinator.station == "PZH"
    # nothing read yet
    assert coordinator.fresh is False
    assert coordinator.level("birch") is None and coordinator.overall_level() is None

    session = FakeSession({pollen_now_url("PZH"): MORNING})
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
    assert coordinator.last_update_success and coordinator.fresh
    assert coordinator.level("birch") == "moderate"
    assert coordinator.level("grasses") == "low"
    assert coordinator.level("oak") is None  # not measured today
    assert coordinator.overall_level() == "moderate"

    coordinator.data.daily_mean = {}
    assert coordinator.overall_level() is None

    # four hours after the newest value the reading is no longer current
    freezer.move_to(datetime(2026, 11, 8, 13, 0, tzinfo=UTC))
    assert coordinator.fresh is True
    freezer.move_to(datetime(2026, 11, 8, 13, 1, tzinfo=UTC))
    assert coordinator.fresh is False


async def test_repair_issue_after_three_failed_reads(hass: HomeAssistant, swiss_now) -> None:
    coordinator = PollenCoordinator(hass, make_entry(hass, {"pollen_station": "PZH"}))
    session = FakeSession({pollen_now_url("PZH"): FakeResponse(503)})
    registry = ir.async_get(hass)
    with patch(SESSION, return_value=session):
        for _attempt in range(2):
            await coordinator.async_refresh()
            assert coordinator.last_update_success is False
            assert registry.async_get_issue(DOMAIN, ISSUE) is None
        await coordinator.async_refresh()
        issue = registry.async_get_issue(DOMAIN, ISSUE)
        assert issue is not None
        assert issue.translation_key == "pollen_unreadable"
        assert issue.translation_placeholders["station"] == "PZH"
        assert "HTTP 503" in issue.translation_placeholders["error"]

        # the next good read withdraws it
        session.routes[pollen_now_url("PZH")] = MORNING
        await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert registry.async_get_issue(DOMAIN, ISSUE) is None
    assert coordinator.data.timestamp == NOW - timedelta(hours=1, minutes=30)
