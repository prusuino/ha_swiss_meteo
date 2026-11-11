"""Shared fixtures for the Swiss Meteo tests.

Nothing is fetched: the readers of the MeteoSwiss files are replaced by
fakes that answer from memory. `setup_integration` loads the integration
for an invented entry (a point in Zürich) at a fixed moment, so the tests
see the same forecast every time.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_component

from custom_components.swiss_meteo.const import DAILY_PARAMS, DOMAIN
from custom_components.swiss_meteo.ogd import ForecastData, ReadStats

# A Sunday morning in November, 11:30 local time in Switzerland.
NOW = datetime(2026, 11, 8, 10, 30, tzinfo=UTC)
RUN = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
ENTRY_ID = "swissmeteotest0001"
SUFFIX = "0001"

ENTRY_DATA: dict[str, Any] = {
    "point_type": 2,
    "point_id": 800100,
    "point_name": "Zürich",
    "point_lat": 47.3769,
    "point_lon": 8.5417,
    "point_height": 408.0,
    "station": "",
    "station_name": "",
    "pollen_station": "",
    "pollen_station_name": "",
    "hourly": True,
    "extended": False,
    "warnings": False,
    "radar": False,
}

# First value of each forecast series; the fakes count up from it.
DAILY_START = {"jp2000d0": 1.0, "tre200px": 10.0, "tre200pn": 2.0, "rka150p0": 0.0, "rreq10p0": 0.0, "rreq90p0": 1.0}
HOURLY_START = {
    "tre200h0": 5.0,
    "jww003i0": 1.0,
    "rre150h0": 0.0,
    "rp0003i0": 10.0,
    "fu3010h0": 8.0,
    "fu3010h1": 20.0,
    "dkl010h0": 230.0,
    "gre000h0": 150.0,
    "sre000h0": 30.0,
}


def make_forecast(run: datetime, point: tuple[int, int], params: tuple[str, ...]) -> ForecastData:
    """A run of eight days and three days of hours, the same on every call."""
    series: dict[str, list[tuple[datetime, float | None]]] = {}
    midnight = run.replace(hour=0, minute=0, second=0, microsecond=0)
    for param in params:
        if param in DAILY_PARAMS:
            start = DAILY_START.get(param, 0.0)
            series[param] = [(midnight + timedelta(days=day), start + day) for day in range(8)]
        else:
            start = HOURLY_START.get(param, 0.5)
            series[param] = [(run + timedelta(hours=hour), start) for hour in range(72)]
    return ForecastData(run=run, point=point, series=series, stats=ReadStats(requests=len(params), bytes=2000 * len(params)))


def find_device(hass: HomeAssistant, identifier: str) -> dr.DeviceEntry | None:
    """The device carrying an identifier of this integration."""
    wanted = (DOMAIN, identifier)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), ENTRY_ID)
    return next((device for device in devices if wanted in device.identifiers), None)


@pytest.fixture
async def swiss_now(hass: HomeAssistant, freezer) -> datetime:
    """Home Assistant in Swiss time, at the fixed moment."""
    await hass.config.async_set_time_zone("Europe/Zurich")
    freezer.move_to(NOW)
    return NOW


@pytest.fixture
def fake_forecast():
    """The run discovery and the forecast read, answered from memory."""

    async def _fetch(_session, run, point, params):
        return make_forecast(run, point, params)

    with (
        patch("custom_components.swiss_meteo.coordinator.async_find_latest_run", return_value=RUN) as find,
        patch("custom_components.swiss_meteo.coordinator.async_fetch_forecast", side_effect=_fetch) as fetch,
    ):
        yield find, fetch


@pytest.fixture
def all_entities_enabled():
    """Create the entities that are off by default as well."""
    with patch("homeassistant.helpers.entity.Entity.entity_registry_enabled_default", return_value=True):
        yield


def make_entry(hass: HomeAssistant, data: dict[str, Any] | None = None, options: dict[str, Any] | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        unique_id="2-800100",
        title="8001 Zürich",
        data={**ENTRY_DATA, **(data or {})},
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def setup_integration(
    hass: HomeAssistant, enable_custom_integrations, swiss_now, fake_forecast
) -> Callable[..., Awaitable[MockConfigEntry]]:
    """Load the integration for the invented entry; keyword arguments
    change the entry data (for example `open_meteo=True`)."""

    async def _setup(options: dict[str, Any] | None = None, **data: Any) -> MockConfigEntry:
        # The recorder is only needed by the history import; mark it as set up.
        mock_component(hass, "recorder")
        entry = make_entry(hass, data, options)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup
