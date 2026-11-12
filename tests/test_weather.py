"""The weather entity: the station's values now, the forecast for the
days and hours to come."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.swiss_meteo.symbols import SYMBOLS

from .conftest import RUN
from .feeds import entity, entity_object, feeds, setup_everything, station_reading

WEATHER = entity("weather")


def attributes(hass: HomeAssistant) -> dict:
    return dict(hass.states.get(WEATHER).attributes)


async def forecasts(hass: HomeAssistant, kind: str) -> list[dict]:
    response = await hass.services.async_call(
        "weather", "get_forecasts", {"entity_id": WEATHER, "type": kind}, blocking=True, return_response=True
    )
    return response[WEATHER]["forecast"]


async def test_station_values_now(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    assert hass.states.get(WEATHER).state == "sunny"
    now = attributes(hass)
    assert (now["temperature"], now["dew_point"], now["humidity"], now["pressure"]) == (7.5, 3.1, 74, 1018.2)
    assert (now["wind_speed"], now["wind_gust_speed"], now["wind_bearing"]) == (9.4, 22.3, 250.0)
    assert (now["symbol"], now["symbol_meaning"]) == (1, "sunny")
    assert (now["precipitation_probability"], now["global_radiation"]) == (10.0, 150.0)
    assert now["forecast_run"] == RUN.isoformat()
    assert (now["point_name"], now["latitude"], now["longitude"], now["elevation"]) == ("Zürich", 47.3769, 8.5417, 408.0)
    assert (now["station"], now["station_time"], now["station_fresh"]) == ("SMA", "2026-11-08T10:20:00+00:00", True)
    assert "zero_degree_level" not in now  # only with the extended parameters
    assert "precipitation_station" not in now  # only with a precipitation station
    assert now["supported_features"] == 3


async def test_precipitation_station_is_named(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, precip_station="WAG")
    now = attributes(hass)
    assert (now["station"], now["precipitation_station"]) == ("SMA", "WAG")


async def test_a_new_station_reading_is_shown_at_once(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_everything(hass, setup_integration)
    with feeds(reading=station_reading(minutes_old=0, tre200s0=9.9)):
        await entry.runtime_data.station.async_refresh()
        await hass.async_block_till_done()
    assert attributes(hass)["temperature"] == 9.9


async def test_night_symbol_after_sunset(hass: HomeAssistant, setup_integration) -> None:
    hass.states.async_set("sun.sun", "below_horizon")
    await setup_everything(hass, setup_integration)
    assert hass.states.get(WEATHER).state == SYMBOLS[101][0]

    hass.states.async_set("sun.sun", "above_horizon")
    weather = entity_object(hass, WEATHER)
    assert weather.condition == "sunny"


async def test_old_station_values_give_way_to_the_forecast(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, reading=station_reading(minutes_old=50))
    now = attributes(hass)
    assert (now["temperature"], now["wind_speed"], now["wind_gust_speed"], now["wind_bearing"]) == (5.0, 8.0, 20.0, 230.0)
    assert "humidity" not in now and "pressure" not in now
    assert now["station_fresh"] is False


async def test_without_a_station(hass: HomeAssistant, setup_integration) -> None:
    await setup_integration()
    now = attributes(hass)
    assert now["temperature"] == 5.0
    assert "station" not in now and "humidity" not in now


async def test_forecast_lists(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    days = await forecasts(hass, "daily")
    assert len(days) == 8
    today, tomorrow = days[0], days[1]
    assert today["datetime"] == "2026-11-08T00:00:00+01:00"
    assert (today["condition"], today["temperature"], today["templow"], today["precipitation"]) == ("sunny", 10.0, 2.0, 0.0)
    assert (tomorrow["temperature"], tomorrow["templow"], tomorrow["precipitation"]) == (11.0, 3.0, 1.0)
    assert (today["wind_speed"], today["wind_gust_speed"], today["precipitation_probability"]) == (8.0, 20.0, 10.0)

    hours = await forecasts(hass, "hourly")
    assert len(hours) > 48
    assert (hours[0]["condition"], hours[0]["temperature"]) == ("sunny", 5.0)


async def test_daily_files_alone(hass: HomeAssistant, setup_integration) -> None:
    await setup_integration(hourly=False)
    # the symbol of the day stands in for the hour's
    assert hass.states.get(WEATHER).state == "sunny"
    now = attributes(hass)
    assert now["symbol"] == 1
    assert "temperature" not in now
    assert now["supported_features"] == 1

    weather = entity_object(hass, WEATHER)
    assert await weather.async_forecast_hourly() is None
    days = await weather.async_forecast_daily()
    assert len(days) == 8
    assert days[0]["native_temperature"] == 10.0
