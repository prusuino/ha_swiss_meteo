"""The binary sensors: rain, frost and strong wind from the hourly
forecast, the official warning, and rain on the radar."""
from __future__ import annotations

import zlib
from array import array
from datetime import timedelta

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.swiss_meteo.binary_sensor import (
    FrostTonightSensor,
    RainApproachingSensor,
    RainExpectedSensor,
    RainingSensor,
    StrongWindExpectedSensor,
    WarningActiveSensor,
)
from custom_components.swiss_meteo.coordinator import ForecastCoordinator
from custom_components.swiss_meteo.meteoalarm import WARNINGS_URL, WarningsCoordinator
from custom_components.swiss_meteo.radar import RadarCoordinator, frame_url

from .conftest import NOW, make_entry
from .fakes import FakeResponse
from .feeds import EVERYTHING, entity, forecast_with, setup_everything
from .test_radar import COLS, ROWS, T


def state(hass: HomeAssistant, key: str) -> str:
    return hass.states.get(entity("binary_sensor", key)).state


def attributes(hass: HomeAssistant, key: str) -> dict:
    return dict(hass.states.get(entity("binary_sensor", key)).attributes)


def dry_radar_file() -> bytes:
    """A frame without any rain."""
    return b"\x89HDF\r\n" + zlib.compress(array("d", bytes(8 * COLS * ROWS)).tobytes())


# --- forecast ----------------------------------------------------------------


async def test_quiet_weather(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    assert state(hass, "rain_expected") == "off"
    rain = attributes(hass, "rain_expected")
    assert (rain["window_hours"], rain["threshold_mm"]) == (6, 0.1)
    assert (rain["precipitation_next_6h"], rain["precipitation_next_24h"]) == (0.0, 0.0)
    assert "next_rain" not in rain

    assert state(hass, "frost_tonight") == "off"
    frost = attributes(hass, "frost_tonight")
    assert (frost["threshold"], frost["night_minimum"]) == (0.0, 5.0)
    assert frost["device_class"] == "cold"

    assert state(hass, "strong_wind_expected") == "off"
    wind = attributes(hass, "strong_wind_expected")
    assert (wind["threshold_kmh"], wind["window_hours"], wind["max_gust"]) == (60.0, 6, 20.0)
    assert wind["max_gust_at"] == "2026-11-08T10:00:00+00:00"


async def test_rain_within_six_hours(hass: HomeAssistant, setup_integration, fake_forecast) -> None:
    fake_forecast[1].side_effect = forecast_with({"rre150h0": {5: 1.2}})
    await setup_integration()
    assert state(hass, "rain_expected") == "on"
    rain = attributes(hass, "rain_expected")
    assert rain["next_rain"] == "2026-11-08T15:00:00+01:00"
    assert rain["next_rain_mm"] == 1.2
    assert rain["hours_until_rain"] in (3, 4)
    assert (rain["precipitation_next_6h"], rain["precipitation_next_24h"]) == (1.2, 1.2)


async def test_rain_comes_into_the_window_with_the_clock(hass: HomeAssistant, setup_integration, fake_forecast, freezer) -> None:
    fake_forecast[1].side_effect = forecast_with({"rre150h0": {9: 0.4}})
    await setup_integration()
    # rain at 18:00 UTC is still more than six hours away
    assert state(hass, "rain_expected") == "off"
    assert attributes(hass, "rain_expected")["next_rain_mm"] == 0.4
    assert attributes(hass, "rain_expected")["precipitation_next_6h"] == 0.0

    # the state is written again shortly after each full hour
    tick = NOW.replace(hour=13, minute=0, second=30)
    freezer.move_to(tick)
    async_fire_time_changed(hass, tick)
    await hass.async_block_till_done()
    assert state(hass, "rain_expected") == "on"
    assert attributes(hass, "rain_expected")["hours_until_rain"] == 5


async def test_frost_tonight(hass: HomeAssistant, setup_integration, fake_forecast) -> None:
    fake_forecast[1].side_effect = forecast_with({"tre200h0": {15: -1.0, 30: -8.0}})
    await setup_integration()
    assert state(hass, "frost_tonight") == "on"
    frost = attributes(hass, "frost_tonight")
    # the colder hour of the night after does not count
    assert frost["night_minimum"] == -1.0
    assert frost["night_minimum_at"] == "2026-11-09T01:00:00+01:00"


async def test_strong_wind_with_an_own_threshold(hass: HomeAssistant, setup_integration) -> None:
    await setup_integration({"gust_threshold": 15})
    assert state(hass, "strong_wind_expected") == "on"
    assert attributes(hass, "strong_wind_expected")["threshold_kmh"] == 15.0


async def test_hours_without_values(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_integration()
    forecast = entry.runtime_data.forecast
    for param in ("tre200h0", "fu3010h1"):
        forecast.data.hourly[param] = [(ts, None) for ts, _value in forecast.data.hourly[param]]

    frost = FrostTonightSensor(hass, entry, forecast)
    assert frost.is_on is False
    assert frost.extra_state_attributes == {"threshold": 0.0}

    wind = StrongWindExpectedSensor(hass, entry, forecast)
    assert wind.is_on is False
    assert (wind.extra_state_attributes["max_gust"], wind.extra_state_attributes["max_gust_at"]) == (None, None)


async def test_daily_files_alone_have_no_hourly_sensors(hass: HomeAssistant, setup_integration) -> None:
    await setup_integration(hourly=False)
    for key in ("rain_expected", "frost_tonight", "strong_wind_expected", "warning_active", "raining"):
        assert hass.states.get(entity("binary_sensor", key)) is None, key


# --- warnings ----------------------------------------------------------------


async def test_warning_in_force(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    assert state(hass, "warning_active") == "on"
    warning = attributes(hass, "warning_active")
    assert (warning["level"], warning["count"], warning["upcoming"]) == ("yellow", 1, 1)
    assert [item["level"] for item in warning["warnings"]] == ["yellow", "red"]
    # the short form leaves the long texts to the level sensor
    assert "description" not in warning["warnings"][0]


async def test_no_warning(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, routes={WARNINGS_URL: FakeResponse(payload={"warnings": []})})
    assert state(hass, "warning_active") == "off"
    warning = attributes(hass, "warning_active")
    assert (warning["level"], warning["count"], warning["upcoming"], warning["warnings"]) == ("none", 0, 0, [])


# --- radar -------------------------------------------------------------------


async def test_rain_on_the_radar(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    assert state(hass, "raining") == "on"
    assert state(hass, "rain_approaching") == "on"
    radar = attributes(hass, "raining")
    assert (radar["rain_rate"], radar["nearest_rain_km"], radar["eta_min"]) == (1.5, 0.0, 0)
    assert radar["radar_time"] == "2026-11-08T10:25:00+00:00"
    assert radar["device_class"] == "moisture"


async def test_dry_radar(hass: HomeAssistant, setup_integration) -> None:
    dry = {frame_url(T): dry_radar_file(), frame_url(T - timedelta(minutes=5)): dry_radar_file()}
    await setup_everything(hass, setup_integration, routes=dry)
    assert state(hass, "raining") == "off"
    assert state(hass, "rain_approaching") == "off"
    radar = attributes(hass, "raining")
    assert radar["rain_rate"] == 0.0
    assert (radar["nearest_rain_km"], radar["eta_min"]) == (None, None)


# --- before the first read ---------------------------------------------------


async def test_nothing_read_yet(hass: HomeAssistant, swiss_now) -> None:
    entry = make_entry(hass, EVERYTHING)
    forecast = ForecastCoordinator(hass, entry)
    radar = RadarCoordinator(hass, entry)
    sensors = [
        RainExpectedSensor(hass, entry, forecast),
        FrostTonightSensor(hass, entry, forecast),
        StrongWindExpectedSensor(hass, entry, forecast),
        WarningActiveSensor(hass, entry, WarningsCoordinator(hass, entry)),
        RainingSensor(hass, entry, radar),
        RainApproachingSensor(hass, entry, radar),
    ]
    for sensor in sensors:
        assert sensor.is_on is None, sensor.entity_id
        assert sensor.extra_state_attributes == {}, sensor.entity_id
        assert sensor.available is False, sensor.entity_id
