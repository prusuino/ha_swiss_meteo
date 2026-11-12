"""The optional Open-Meteo part: parsing, the one request, the coordinator's
behaviour over an outage, and the entities of the separate device. The API
is never called; the answers are built here."""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.swiss_meteo.const import ATTRIBUTION_OPEN_METEO, DOMAIN, USER_AGENT, VERSION
from custom_components.swiss_meteo.device import open_meteo_device_info
from custom_components.swiss_meteo.open_meteo import (
    API_URL,
    HOURLY_PARAMS,
    OpenMeteoData,
    OpenMeteoError,
    aqi_level,
    async_fetch_open_meteo,
    parse_open_meteo,
    request_params,
)

from .conftest import ENTRY_ID, NOW, SUFFIX, find_device, make_entry

FETCH = "custom_components.swiss_meteo.open_meteo.async_fetch_open_meteo"
# Local midnight of 8 November in Switzerland (UTC+1): the series starts there.
START = datetime(2026, 11, 7, 23, 0, tzinfo=UTC)
HOURS = 96


def make_payload(hours: int = HOURS, start: datetime = START) -> dict:
    """An answer in the shape of the API, with values that are easy to check:
    the running hour at NOW is index 11."""
    index = range(hours)
    uv = [max(0.0, 3.0 - abs((i % 24) - 12) * 0.5) for i in index]
    return {
        "latitude": 47.4,
        "longitude": 8.5,
        "hourly_units": {"time": "unixtime", "european_aqi": "EAQI"},
        "hourly": {
            "time": [int((start + timedelta(hours=i)).timestamp()) for i in index],
            "european_aqi": [20 + (i % 24) + 10 * (i // 24) for i in index],
            "pm10": [round(10.0 + i * 0.1, 1) for i in index],
            "pm2_5": [5.0 for _ in index],
            "nitrogen_dioxide": [12.5 for _ in index],
            "ozone": [40.0 for _ in index],
            "uv_index": uv,
            "uv_index_clear_sky": [value + 1.0 for value in uv],
            # out of season the model has no values at all
            "alder_pollen": [None for _ in index],
            "birch_pollen": [0.0 if i < hours - 23 else None for i in index],
            "grass_pollen": [float(i) for i in index],
            "mugwort_pollen": [0.0 for _ in index],
            "olive_pollen": [0.0 for _ in index],
            "ragweed_pollen": [2.0 for _ in index],
        },
    }


def make_data(fetched: datetime = NOW, **kwargs) -> OpenMeteoData:
    return parse_open_meteo(make_payload(**kwargs), fetched)


def entity(key: str) -> str:
    return f"sensor.{DOMAIN}_{SUFFIX}_{key}"


# --- pure helpers -------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "level"),
    [(None, None), (0, "good"), (20, "good"), (20.1, "fair"), (40, "fair"), (55, "moderate"), (80, "poor"), (100, "very_poor"), (140, "extremely_poor")],
)
def test_aqi_level(value, level) -> None:
    assert aqi_level(value) == level


def test_parse_reads_every_requested_series() -> None:
    data = make_data()
    assert len(data.times) == HOURS
    assert data.times[0] == START
    assert set(data.series) == set(HOURLY_PARAMS)
    assert data.series["alder_pollen"][0] is None
    assert data.fetched == NOW


def test_parse_skips_unusable_series_and_values() -> None:
    payload = make_payload(hours=4)
    payload["hourly"]["pm10"] = [1, "2", True, None]  # only real numbers count
    payload["hourly"]["ozone"] = [1.0, 2.0]  # wrong length
    payload["hourly"]["uv_index"] = "n/a"
    data = parse_open_meteo(payload, NOW)
    assert data.series["pm10"] == (1.0, None, None, None)
    assert "ozone" not in data.series
    assert "uv_index" not in data.series


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (["not", "an", "object"], "not a JSON object"),
        ({"error": True, "reason": "Latitude must be in range of -90 to 90"}, "Latitude must be"),
        ({"error": True}, "error reported"),
        ({"hourly": []}, "no hourly values"),
        ({"hourly": {"time": []}}, "no time axis"),
        ({"hourly": {"time": ["2026-11-08T00:00"]}}, "time axis is not readable"),
        ({"hourly": {"time": [1794092400], "something_else": [1]}}, "none of the requested values"),
    ],
)
def test_parse_refuses_unusable_answers(payload, message) -> None:
    with pytest.raises(OpenMeteoError, match=message):
        parse_open_meteo(payload, NOW)


async def test_series_lookups(hass: HomeAssistant, swiss_now) -> None:
    data = make_data()
    assert data.index_at(NOW) == 11
    assert data.index_at(START) == 0
    assert data.index_at(START - timedelta(seconds=1)) is None
    assert data.index_at(START + timedelta(hours=HOURS) - timedelta(seconds=1)) == HOURS - 1
    assert data.index_at(START + timedelta(hours=HOURS)) is None
    assert data.value("european_aqi", NOW) == 31
    assert data.value("unknown", NOW) is None
    assert data.value("european_aqi", START - timedelta(hours=1)) is None

    # 12:00 local is 11:00 UTC
    assert data.day_peak("uv_index", date(2026, 11, 8)) == (3.0, datetime(2026, 11, 8, 11, 0, tzinfo=UTC))
    assert data.day_max("european_aqi", date(2026, 11, 8)) == 43
    assert data.day_max("european_aqi", date(2026, 11, 9)) == 53
    assert data.day_max("alder_pollen", date(2026, 11, 8)) is None
    assert data.day_max("european_aqi", date(2026, 12, 1)) is None
    assert data.daily_max("grass_pollen") == {"2026-11-08": 23.0, "2026-11-09": 47.0, "2026-11-10": 71.0, "2026-11-11": 95.0}
    assert data.daily_max("alder_pollen") == {}
    assert OpenMeteoData(fetched=NOW, times=(), series={}).index_at(NOW) is None


def test_request_rounds_the_coordinates() -> None:
    params = request_params(47.376912, 8.541694)
    assert params["latitude"] == "47.38"
    assert params["longitude"] == "8.54"
    assert params["hourly"].split(",") == list(HOURLY_PARAMS)
    assert params["forecast_days"] == "4"
    assert params["timeformat"] == "unixtime"


# --- the request ---------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int = 200, payload=None, error: Exception | None = None) -> None:
        self.status = status
        self._payload = payload
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def json(self, content_type=None):
        if self._error is not None:
            raise self._error
        return self._payload


class FakeSession:
    """Stands in for the aiohttp session and remembers what was asked."""

    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if self._error is not None:
            raise self._error
        return self._response


async def test_fetch_asks_once_and_identifies_itself(hass: HomeAssistant, swiss_now) -> None:
    session = FakeSession(FakeResponse(payload=make_payload()))
    data = await async_fetch_open_meteo(session, 47.3769, 8.5417)
    assert data.value("ozone", NOW) == 40.0
    assert data.fetched == NOW
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == API_URL
    assert kwargs["params"]["latitude"] == "47.38"
    assert kwargs["headers"]["User-Agent"] == USER_AGENT
    # the version in the header follows the manifest
    assert USER_AGENT.startswith(f"SwissMeteo/{VERSION} ")


@pytest.mark.parametrize(
    ("session", "message"),
    [
        (FakeSession(FakeResponse(status=429)), "answered 429"),
        (FakeSession(error=aiohttp.ClientConnectionError("no route")), "no route"),
        (FakeSession(error=TimeoutError()), "TimeoutError"),
        (FakeSession(FakeResponse(error=ValueError("not JSON"))), "not JSON"),
        (FakeSession(FakeResponse(payload={"error": True, "reason": "bad request"})), "bad request"),
    ],
)
async def test_fetch_failures_become_one_error(session, message) -> None:
    with pytest.raises(OpenMeteoError, match=message):
        await async_fetch_open_meteo(session, 47.0, 8.0)


# --- entities ------------------------------------------------------------------


async def test_off_by_default(hass: HomeAssistant, setup_integration) -> None:
    with patch(FETCH) as fetch:
        entry = await setup_integration()
    fetch.assert_not_called()
    assert entry.runtime_data.open_meteo is None
    assert hass.states.get(entity("air_quality_index")) is None
    assert find_device(hass, f"{ENTRY_ID}_open_meteo") is None


async def test_sensors_of_the_separate_device(hass: HomeAssistant, setup_integration, caplog) -> None:
    with patch(FETCH, return_value=make_data()) as fetch:
        entry = await setup_integration(open_meteo=True)
    fetch.assert_called_once()
    assert fetch.call_args.args[1:] == (47.3769, 8.5417)

    state = hass.states.get(entity("air_quality_index"))
    assert float(state.state) == 31
    assert state.attributes["attribution"] == ATTRIBUTION_OPEN_METEO
    assert state.attributes["device_class"] == "aqi"
    assert state.attributes["today_max"] == 43
    assert state.attributes["tomorrow_max"] == 53
    assert state.attributes["model_read"] == NOW.isoformat()

    level = hass.states.get(entity("air_quality_level"))
    assert level.state == "fair"
    assert level.attributes["index"] == 31
    assert level.attributes["today_worst"] == "moderate"
    assert level.attributes["tomorrow_worst"] == "moderate"
    assert level.attributes["options"] == ["good", "fair", "moderate", "poor", "very_poor", "extremely_poor"]

    assert float(hass.states.get(entity("pm10")).state) == 11.1
    assert float(hass.states.get(entity("pm2_5")).state) == 5.0
    assert float(hass.states.get(entity("nitrogen_dioxide")).state) == 12.5
    assert float(hass.states.get(entity("ozone")).state) == 40.0
    assert hass.states.get(entity("pm10")).attributes["unit_of_measurement"].endswith("g/m³")

    uv = hass.states.get(entity("uv_index"))
    assert float(uv.state) == 2.5
    assert uv.attributes["today_max"] == 3.0
    peak = hass.states.get(entity("uv_index_max_today"))
    assert float(peak.state) == 3.0
    assert peak.attributes["time"] == "2026-11-08T12:00:00+01:00"
    assert peak.attributes["clear_sky_max"] == 4.0
    assert peak.attributes["tomorrow_max"] == 3.0

    grass = hass.states.get(entity("pollen_forecast_grass"))
    assert float(grass.state) == 11
    assert grass.attributes["unit_of_measurement"] == "grains/m³"
    assert grass.attributes["today_max"] == 23.0
    assert grass.attributes["tomorrow_max"] == 47.0
    assert list(grass.attributes["daily_max"]) == ["2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11"]
    # no model values out of season: unknown, not unavailable
    assert hass.states.get(entity("pollen_forecast_alder")).state == "unknown"
    assert float(hass.states.get(entity("pollen_forecast_ragweed")).state) == 2.0

    entities = er.async_get(hass)
    main = find_device(hass, ENTRY_ID)
    own = find_device(hass, f"{ENTRY_ID}_open_meteo")
    assert own is not None and own.id != main.id
    assert own.via_device_id == main.id
    # linked the way current Home Assistant wants it, without a deprecated call
    assert "deprecated" not in caplog.text
    assert own.manufacturer == "Open-Meteo"
    assert own.name == "Open-Meteo Zürich"
    assert "not official" in own.model
    # every Open-Meteo sensor sits on that device, the MeteoSwiss ones do not
    own_entities = er.async_entries_for_device(entities, own.id, include_disabled_entities=True)
    assert len(own_entities) == 14
    assert entities.async_get(entity("today_max")).device_id == main.id
    # olive trees hardly matter north of the Alps: off until wanted
    olive = entities.async_get(entity("pollen_forecast_olive"))
    assert olive.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(entity("pollen_forecast_olive")) is None
    assert entry.runtime_data.open_meteo.fresh


async def test_device_link_by_id_or_by_identifier(hass: HomeAssistant, enable_custom_integrations) -> None:
    """Older Home Assistant names the parent device by its identifier;
    current versions want the registry id, which needs the main device to
    be registered first."""
    entry = make_entry(hass)
    with patch("custom_components.swiss_meteo.device.links_by_device_id", return_value=False):
        info = open_meteo_device_info(hass, entry)
    assert info["via_device"] == (DOMAIN, ENTRY_ID)
    assert "via_device_id" not in info
    assert find_device(hass, ENTRY_ID) is None

    info = open_meteo_device_info(hass, entry)
    main = find_device(hass, ENTRY_ID)
    assert main is not None and info["via_device_id"] == main.id
    assert "via_device" not in info
    # every further entity gets the same device, not a second one
    assert open_meteo_device_info(hass, entry)["via_device_id"] == main.id
    assert len(dr.async_entries_for_config_entry(dr.async_get(hass), ENTRY_ID)) == 1


async def test_state_follows_the_running_hour(hass: HomeAssistant, setup_integration, freezer) -> None:
    with patch(FETCH, return_value=make_data()) as fetch:
        await setup_integration(open_meteo=True)
        assert float(hass.states.get(entity("air_quality_index")).state) == 31
        tick = NOW.replace(hour=11, minute=0, second=10)
        freezer.move_to(tick)
        async_fire_time_changed(hass, tick)
        await hass.async_block_till_done()
    # the next hour's value, without another request
    assert float(hass.states.get(entity("air_quality_index")).state) == 32
    assert hass.states.get(entity("air_quality_level")).state == "fair"
    assert fetch.call_count == 1


async def test_outage_keeps_the_forecast_then_gives_up(
    hass: HomeAssistant, setup_integration, freezer, caplog: pytest.LogCaptureFixture
) -> None:
    with patch(FETCH, return_value=make_data()):
        entry = await setup_integration(open_meteo=True)
    coordinator = entry.runtime_data.open_meteo
    issues = ir.async_get(hass)
    issue_id = f"open_meteo_unreachable_{ENTRY_ID}"

    caplog.set_level(logging.INFO)
    with patch(FETCH, side_effect=OpenMeteoError("Open-Meteo answered 502")):
        for hour in range(1, 6):
            freezer.move_to(NOW + timedelta(hours=hour))
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            assert coordinator.last_update_success  # the kept series still covers the hour
            assert issues.async_get_issue(DOMAIN, issue_id) is None
        assert float(hass.states.get(entity("air_quality_index")).state) == 36
        # said once, not every hour
        assert caplog.text.count("keeping the last forecast") == 1

        # the sixth failed read in a row raises the repair notice
        freezer.move_to(NOW + timedelta(hours=6))
        await coordinator.async_refresh()
        issue = issues.async_get_issue(DOMAIN, issue_id)
        assert issue is not None
        assert issue.translation_key == "open_meteo_unreachable"
        assert issue.translation_placeholders == {"error": "Open-Meteo answered 502"}

        # after twelve hours the kept series is no forecast any more
        freezer.move_to(NOW + timedelta(hours=13))
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert not coordinator.last_update_success
        assert isinstance(coordinator.last_exception, UpdateFailed)
        assert hass.states.get(entity("air_quality_index")).state == "unavailable"

    with patch(FETCH, return_value=make_data(fetched=NOW + timedelta(hours=14))):
        freezer.move_to(NOW + timedelta(hours=14))
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert coordinator.last_update_success
    assert "readable again" in caplog.text
    assert issues.async_get_issue(DOMAIN, issue_id) is None
    assert float(hass.states.get(entity("air_quality_index")).state) == 20 + 1 + 10  # index 25


async def test_series_run_out_makes_the_sensors_unavailable(hass: HomeAssistant, setup_integration, freezer) -> None:
    """A series that no longer covers the running hour is not shown, even
    while the coordinator itself reports success."""
    with patch(FETCH, return_value=make_data(hours=12)):
        entry = await setup_integration(open_meteo=True)
        assert float(hass.states.get(entity("air_quality_index")).state) == 31
        tick = NOW.replace(hour=11, minute=0, second=10)
        freezer.move_to(tick)
        async_fire_time_changed(hass, tick)
        await hass.async_block_till_done()
    assert not entry.runtime_data.open_meteo.fresh
    assert hass.states.get(entity("air_quality_index")).state == "unavailable"
    assert hass.states.get(entity("uv_index_max_today")).state == "unavailable"


async def test_setup_survives_an_unreachable_api(
    hass: HomeAssistant, setup_integration, caplog: pytest.LogCaptureFixture
) -> None:
    with patch(FETCH, side_effect=OpenMeteoError("no route")):
        entry = await setup_integration(open_meteo=True)
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert "Open-Meteo not readable yet" in caplog.text
    assert hass.states.get(entity("air_quality_index")).state == "unavailable"
    assert hass.states.get(entity("air_quality_level")).state == "unavailable"
    assert hass.states.get(entity("pollen_forecast_grass")).state == "unavailable"
    # the MeteoSwiss part is not affected
    assert hass.states.get(f"weather.{DOMAIN}_{SUFFIX}").state != "unavailable"


# --- switching it on and off -----------------------------------------------------


async def test_options_switch_it_on_and_off_again(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_integration()
    entities = er.async_get(hass)
    lists = (
        patch("custom_components.swiss_meteo.config_flow.async_fetch_stations", return_value=[]),
        patch("custom_components.swiss_meteo.config_flow.async_fetch_precip_stations", return_value=[]),
        patch("custom_components.swiss_meteo.config_flow.async_fetch_pollen_stations", return_value=[]),
    )

    async def _set(value: bool) -> None:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        user_input = {"hourly": True, "extended": False, "warnings": False, "radar": False, "gust_threshold": 60,
                      "station": "none", "pollen_station": "none", "open_meteo": value}
        result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

    with lists[0], lists[1], lists[2], patch(FETCH, return_value=make_data()):
        await _set(True)
        assert entry.options["open_meteo"] is True
        assert float(hass.states.get(entity("air_quality_index")).state) == 31
        assert find_device(hass, f"{ENTRY_ID}_open_meteo") is not None

        await _set(False)
    assert entry.options["open_meteo"] is False
    assert entry.runtime_data.open_meteo is None
    # the device goes, and its entities with it; the MeteoSwiss device stays
    assert find_device(hass, f"{ENTRY_ID}_open_meteo") is None
    assert entities.async_get(entity("air_quality_index")) is None
    assert find_device(hass, ENTRY_ID) is not None
    assert entities.async_get(entity("today_max")) is not None


async def test_unload_withdraws_the_repair_notice(hass: HomeAssistant, setup_integration, freezer) -> None:
    with patch(FETCH, return_value=make_data()):
        entry = await setup_integration(open_meteo=True)
    coordinator = entry.runtime_data.open_meteo
    coordinator.issues.raise_now("open_meteo_unreachable", {"error": "x"})
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"open_meteo_unreachable_{ENTRY_ID}") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, f"open_meteo_unreachable_{ENTRY_ID}") is None
