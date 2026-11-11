"""Everything the integration reads besides the forecast, served from
memory: the station's newest values, a pollen station's hours, the alert
feed and two radar frames. `setup_everything` loads the invented entry
with all of it switched on."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.swiss_meteo.const import DOMAIN
from custom_components.swiss_meteo.meteoalarm import WARNINGS_URL
from custom_components.swiss_meteo.ogd import StationReading
from custom_components.swiss_meteo.pollen import pollen_now_url
from custom_components.swiss_meteo.radar import frame_url

from .conftest import NOW, SUFFIX, make_forecast
from .fakes import FakeResponse, FakeSession
from .test_meteoalarm import TWO_WARNINGS
from .test_pollen import MORNING
from .test_radar import T, radar_file

READING = "custom_components.swiss_meteo.coordinator.async_fetch_station_reading"
SESSIONS = tuple(f"custom_components.swiss_meteo.{module}.async_get_clientsession" for module in ("pollen", "meteoalarm", "radar"))
RADAR_ASYNCIO = "custom_components.swiss_meteo.radar.asyncio"

# Station, pollen station, warnings and radar switched on.
EVERYTHING: dict[str, Any] = {"station": "SMA", "pollen_station": "PZH", "warnings": True, "radar": True}

STATION_VALUES = {
    "tre200s0": 7.5,
    "tde200s0": 3.1,
    "ure200s0": 74.0,
    "pp0qnhs0": 1018.2,
    "fu3010z0": 9.4,
    "fu3010z1": 22.3,
    "dkl010z0": 250.0,
    "rre150z0": 0.2,
    "sre000z0": 4.0,
    "gre000z0": 180.0,
    "htoauts0": 0.0,
}


def station_reading(minutes_old: int = 10, **values: float) -> StationReading:
    return StationReading(abbr="SMA", timestamp=NOW - timedelta(minutes=minutes_old), values={**STATION_VALUES, **values})


def entity(domain: str, key: str = "") -> str:
    """The entity id of the invented entry for a key ("" is the weather entity)."""
    return f"{domain}.{DOMAIN}_{SUFFIX}_{key}" if key else f"{domain}.{DOMAIN}_{SUFFIX}"


def entity_object(hass: HomeAssistant, entity_id: str) -> Any:
    """The entity behind a state, to call its methods."""
    return hass.data[entity_id.split(".")[0]].get_entity(entity_id)


def forecast_with(hours: dict[str, dict[int, float | None]]):
    """A forecast read whose hourly series differ at single hours after the
    run: `{"rre150h0": {5: 1.2}}` puts 1.2 mm into the sixth hour. Meant as
    the side effect of the read that `fake_forecast` patches."""

    async def _fetch(_session, run, point, params):
        data = make_forecast(run, point, params)
        for param, values in hours.items():
            if param not in data.series:
                continue
            for hour, value in values.items():
                data.series[param][hour] = (data.series[param][hour][0], value)
        return data

    return _fetch


def all_routes() -> dict[str, Any]:
    return {
        pollen_now_url("PZH"): MORNING,
        WARNINGS_URL: FakeResponse(payload=TWO_WARNINGS),
        frame_url(T): radar_file(),
        frame_url(T - timedelta(minutes=5)): radar_file(),
    }


@contextmanager
def feeds(routes: dict[str, Any] | None = None, reading: Any = None) -> Iterator[FakeSession]:
    """Serve the files from memory. `routes` replaces single files (an
    exception or an error response makes that read fail), `reading` is the
    station's answer (an exception makes it fail)."""
    session = FakeSession({**all_routes(), **(routes or {})})
    answer = reading if reading is not None else station_reading()
    station = {"side_effect": answer} if isinstance(answer, Exception) else {"return_value": answer}
    with (
        patch(READING, **station),
        patch(SESSIONS[0], return_value=session),
        patch(SESSIONS[1], return_value=session),
        patch(SESSIONS[2], return_value=session),
        patch(RADAR_ASYNCIO, SimpleNamespace(sleep=AsyncMock())),
    ):
        yield session


async def setup_everything(
    hass: HomeAssistant,
    setup_integration,
    options: dict[str, Any] | None = None,
    *,
    routes: dict[str, Any] | None = None,
    reading: Any = None,
    **data: Any,
) -> MockConfigEntry:
    """Load the entry with everything on and wait for the radar history;
    `routes` and `reading` are handed to `feeds`."""
    with feeds(routes, reading):
        entry = await setup_integration(options, **{**EVERYTHING, **data})
        await hass.async_block_till_done(wait_background_tasks=True)
    return entry
