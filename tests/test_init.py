"""Setting up and unloading an entry, the two actions and the radar
frames for the card."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir

from custom_components.swiss_meteo import async_unload_entry
from custom_components.swiss_meteo.const import DOMAIN
from custom_components.swiss_meteo.device import device_info
from custom_components.swiss_meteo.frontend import _REGISTERED_FLAG, async_serve_frontend
from custom_components.swiss_meteo.history import GROUPS, HistoryError
from custom_components.swiss_meteo.meteoalarm import WARNINGS_URL
from custom_components.swiss_meteo.ogd import OgdError
from custom_components.swiss_meteo.pollen import pollen_now_url
from custom_components.swiss_meteo.radar import frame_url

from .conftest import ENTRY_ID, RUN, make_entry
from .fakes import FakeResponse
from .feeds import entity, setup_everything
from .test_radar import T

IMPORT = "custom_components.swiss_meteo.async_import_history"
BEST_WINDOW = "custom_components.swiss_meteo.best_window"


async def call(hass: HomeAssistant, action: str, **data) -> dict:
    return await hass.services.async_call(DOMAIN, action, data, blocking=True, return_response=True)


def add_issue(hass: HomeAssistant, issue_id: str) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="pollen_unreadable",
        translation_placeholders={"station": "PZH", "error": "HTTP 503"},
    )


# --- setting up --------------------------------------------------------------


async def test_feeds_that_cannot_be_read_do_not_block_the_forecast(
    hass: HomeAssistant, setup_integration, caplog: pytest.LogCaptureFixture
) -> None:
    down = {
        pollen_now_url("PZH"): FakeResponse(503),
        WARNINGS_URL: FakeResponse(503),
        frame_url(T): FakeResponse(503),
        frame_url(T - timedelta(minutes=5)): FakeResponse(503),
    }
    entry = await setup_everything(hass, setup_integration, routes=down, reading=OgdError("station file of SMA has no rows"))

    assert entry.state is ConfigEntryState.LOADED
    for line in (
        "Entry 0001: station SMA not readable yet, its sensors start unavailable",
        "Entry 0001: pollen station PZH not readable yet, its sensors start unavailable",
        "Entry 0001: warnings feed not readable yet, the warning entities start unavailable",
        "Entry 0001: radar not readable yet, its entities start unavailable",
    ):
        assert line in caplog.text, line
    # the forecast is there, the rest waits for its first read
    assert hass.states.get(entity("weather")).state == "sunny"
    assert hass.states.get(entity("sensor", "forecast_run")).state == RUN.isoformat()
    for domain, key in (
        ("sensor", "temperature"),
        ("sensor", "pollen_birch"),
        ("sensor", "warning_level"),
        ("binary_sensor", "warning_active"),
        ("binary_sensor", "raining"),
        ("image", "radar"),
    ):
        assert hass.states.get(entity(domain, key)).state == "unavailable", key


async def test_point_outside_the_radar_composite(
    hass: HomeAssistant, setup_integration, caplog: pytest.LogCaptureFixture
) -> None:
    entry = await setup_everything(hass, setup_integration, point_lat=60.0, point_lon=30.0)
    assert entry.state is ConfigEntryState.LOADED
    assert "Entry 0001: point outside the radar composite, radar disabled" in caplog.text
    assert entry.runtime_data.radar is None
    assert hass.states.get(entity("image", "radar")) is None
    assert hass.states.get(entity("binary_sensor", "raining")) is None


async def test_unload_withdraws_the_repair_issues(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_integration()
    registry = ir.async_get(hass)
    own, foreign = f"pollen_unreadable_PZH_{ENTRY_ID}", "pollen_unreadable_PZH_anotherentry0002"
    add_issue(hass, own)
    add_issue(hass, foreign)

    # platforms that do not unload leave the issues alone
    with patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=False)):
        assert await async_unload_entry(hass, entry) is False
    assert registry.async_get_issue(DOMAIN, own) is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert registry.async_get_issue(DOMAIN, own) is None
    assert registry.async_get_issue(DOMAIN, foreign) is not None


async def test_card_files_are_served_once(hass: HomeAssistant) -> None:
    register = AsyncMock(side_effect=RuntimeError("no web server yet"))
    hass.http = SimpleNamespace(async_register_static_paths=register)
    with pytest.raises(RuntimeError):
        await async_serve_frontend(hass)
    # a failed attempt may be repeated
    assert _REGISTERED_FLAG not in hass.data

    register.side_effect = None
    await async_serve_frontend(hass)
    await async_serve_frontend(hass)
    assert register.call_count == 2
    assert register.call_args.args[0][0].url_path == "/swiss_meteo_files"


async def test_device_model(hass: HomeAssistant) -> None:
    model = device_info(hass, make_entry(hass, {"station": "SMA", "pollen_station": "PZH"}))["model"]
    assert "SMA" in model and "pollen PZH" in model
    assert model.endswith("· 408 m")

    named = device_info(
        hass, make_entry(hass, {"station": "SMA", "station_name": "Zürich / Fluntern", "pollen_station": "PZH", "pollen_station_name": "Zürich"})
    )["model"]
    assert "Zürich / Fluntern" in named and "pollen Zürich" in named

    without_height = device_info(hass, make_entry(hass, {"point_height": None}))["model"]
    assert " m" not in without_height and "pollen" not in without_height


async def test_device_model_with_a_precipitation_station(hass: HomeAssistant) -> None:
    both = {"station": "SMA", "precip_station": "WAG", "precip_station_name": "Waldegg", "pollen_station": "PZH"}
    model = device_info(hass, make_entry(hass, both))["model"]
    assert "SMA" in model and "precipitation Waldegg, pollen PZH" in model

    alone = device_info(hass, make_entry(hass, {"precip_station": "WAG"}))["model"]
    assert "precipitation WAG" in alone and "SMA" not in alone

    # switched off in the Configure dialog: the options count
    off = device_info(hass, make_entry(hass, both, {"precip_station": "", "precip_station_name": ""}))["model"]
    assert "precipitation" not in off


async def test_precipitation_station_that_cannot_be_read_does_not_block_the_rest(
    hass: HomeAssistant, setup_integration, caplog: pytest.LogCaptureFixture
) -> None:
    entry = await setup_everything(
        hass, setup_integration, precip=OgdError("station file of WAG has no rows"), precip_station="WAG"
    )
    assert entry.state is ConfigEntryState.LOADED
    assert "Entry 0001: precipitation station WAG not readable yet, its sensor starts unavailable" in caplog.text
    assert hass.states.get(entity("sensor", "precipitation")).state == "unavailable"
    assert hass.states.get(entity("sensor", "temperature")).state == "7.5"


# --- best_window -------------------------------------------------------------


async def test_best_window(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_integration()
    window = await call(hass, "best_window", entry=entry.entry_id)
    assert window["found"] is True
    assert window["criterion"] == "dry"
    assert window["precipitation_mm"] == 0.0
    assert (window["max_gust_kmh"], window["mean_temperature"]) == (20.0, 5.0)
    assert window["start"] < window["end"]

    sunny = await call(hass, "best_window", entry=entry.entry_id, hours=2, within=12, criterion="sunny")
    assert (sunny["found"], sunny["criterion"]) == (True, "sunny")


async def test_best_window_without_a_full_window(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_integration()
    with patch(BEST_WINDOW, return_value=None):
        assert await call(hass, "best_window", entry=entry.entry_id, criterion="calm") == {"found": False, "criterion": "calm"}


async def test_best_window_refuses(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_integration(hourly=False)
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "best_window", entry=entry.entry_id)
    assert error.value.translation_key == "no_hourly"

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "best_window", entry="no such entry")
    assert error.value.translation_key == "entry_not_loaded"


# --- import_history ----------------------------------------------------------


async def test_import_history(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_everything(hass, setup_integration)
    answer = {"station": "SMA", "rows": 26280}
    with patch(IMPORT, AsyncMock(return_value=answer)) as importer:
        assert await call(hass, "import_history", entry=entry.entry_id) == answer
        order = importer.call_args.kwargs
        assert (order["station"], order["entry_id"], order["statistic_prefix"]) == ("SMA", ENTRY_ID, "0001")
        assert order["precip_station"] == ""
        assert (order["years"], order["resolution"]) == (3, "hourly")
        assert order["groups"] == set(GROUPS)
        assert order["units"]["temperature"] == "°C"

        await call(hass, "import_history", entry=entry.entry_id, years=40, resolution="daily", values=["temperature", "wind"])
        order = importer.call_args.kwargs
        assert (order["years"], order["resolution"], order["groups"]) == (40, "daily", {"temperature", "wind"})

    # what the import reads counts towards the day's traffic
    forecast = entry.runtime_data.forecast
    before = (forecast.data.requests_today, forecast.data.bytes_today)
    order["account"](3, 9000)
    await hass.async_block_till_done()
    assert (forecast.data.requests_today, forecast.data.bytes_today) == (before[0] + 3, before[1] + 9000)
    assert hass.states.get(entity("sensor", "traffic_today")).attributes["last_read_requests"] == 3

    forecast.data = None
    order["account"](1, 100)  # nothing to count on yet: ignored


async def test_import_history_with_a_precipitation_station(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_everything(hass, setup_integration, precip_station="WAG")
    with patch(IMPORT, AsyncMock(return_value={})) as importer:
        await call(hass, "import_history", entry=entry.entry_id)
    order = importer.call_args.kwargs
    assert (order["station"], order["precip_station"]) == ("SMA", "WAG")


async def test_import_history_with_a_precipitation_station_alone(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_everything(hass, setup_integration, station="", precip_station="WAG")
    with patch(IMPORT, AsyncMock(return_value={})) as importer:
        await call(hass, "import_history", entry=entry.entry_id)
    order = importer.call_args.kwargs
    assert (order["station"], order["precip_station"]) == ("", "WAG")


async def test_import_history_refuses(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_integration()
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "import_history", entry=entry.entry_id)
    assert error.value.translation_key == "no_station"

    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "import_history", entry="no such entry")
    assert error.value.translation_key == "entry_not_loaded"

    # an entry that is known but not loaded is refused the same way
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(ServiceValidationError) as error:
        await call(hass, "import_history", entry=entry.entry_id)
    assert error.value.translation_key == "entry_not_loaded"


async def test_import_history_limits_the_hourly_years(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_everything(hass, setup_integration)
    with patch(IMPORT, AsyncMock(return_value={})) as importer:
        with pytest.raises(ServiceValidationError) as error:
            await call(hass, "import_history", entry=entry.entry_id, years=21)
        assert error.value.translation_key == "hourly_years"
        assert importer.call_count == 0

        importer.side_effect = HistoryError("the archive of SMA could not be read")
        with pytest.raises(HomeAssistantError, match="the archive of SMA could not be read"):
            await call(hass, "import_history", entry=entry.entry_id, years=20)


# --- radar frames for the card -----------------------------------------------


async def test_radar_frames_for_the_card(hass: HomeAssistant, setup_integration, hass_ws_client) -> None:
    await setup_everything(hass, setup_integration)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "swiss_meteo/radar_frames", "entity_id": entity("image", "radar")})
    answer = await client.receive_json()
    assert answer["success"] is True
    loop = answer["result"]
    assert loop["km_per_px"] == 1
    assert loop["newest"] == T.isoformat()
    assert loop["center"]["row"] == loop["center"]["col"]
    assert len(loop["frames"]) >= 2
    assert "not an official nowcast" in loop["estimate"]

    hass.states.async_set("sensor.something_else", "1")
    await client.send_json_auto_id({"type": "swiss_meteo/radar_frames", "entity_id": "sensor.something_else"})
    answer = await client.receive_json()
    assert answer["success"] is False
    assert answer["error"]["code"] == "not_found"


async def test_no_radar_frames_without_radar(hass: HomeAssistant, setup_integration, hass_ws_client) -> None:
    await setup_integration()
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "swiss_meteo/radar_frames", "entity_id": entity("weather")})
    answer = await client.receive_json()
    assert answer["success"] is False
    assert answer["error"]["code"] == "not_found"
