"""The everyday questions (laundry, windscreen, airing at night, watering)
from the hourly forecast, and from the station what the air feels like and
where the pressure is going."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.swiss_meteo.coordinator import StationCoordinator
from custom_components.swiss_meteo.derived import apparent_temperature, pressure_trend
from custom_components.swiss_meteo.ogd import StationReading, async_fetch_station_reading, station_now_url

from .conftest import NOW, make_entry
from .fakes import FakeSession
from .feeds import READING, entity, forecast_with, setup_everything, station_reading


def state(hass: HomeAssistant, key: str, domain: str = "binary_sensor") -> str:
    return hass.states.get(entity(domain, key)).state


def attributes(hass: HomeAssistant, key: str, domain: str = "binary_sensor") -> dict:
    return dict(hass.states.get(entity(domain, key)).attributes)


# The run starts at 10:00 local time; hour n of a series is 10:00 + n.


async def test_a_dry_cool_november_day(hass: HomeAssistant, setup_integration) -> None:
    await setup_integration()
    # dry from now (11:00) to 20:00, at 5 °C: good enough for the laundry
    assert state(hass, "laundry_weather") == "on"
    laundry = attributes(hass, "laundry_weather")
    assert laundry["dry_hours"] == 9 and laundry["required_hours"] == 4
    assert (laundry["window_start"], laundry["window_end"]) == ("2026-11-08T11:00:00+01:00", "2026-11-08T20:00:00+01:00")
    assert state(hass, "frozen_windscreen") == "off"
    assert attributes(hass, "frozen_windscreen")["morning_minimum"] == 5.0
    assert state(hass, "cool_night") == "off"  # no hot day
    assert state(hass, "watering_needed") == "off"  # no warm day
    assert attributes(hass, "watering_needed")["precipitation_next_48h"] == 0.0


async def test_laundry_needs_four_dry_hours_in_a_row(hass: HomeAssistant, setup_integration, fake_forecast) -> None:
    # rain at 14:00, a high chance of rain at 18:00: three dry hours at most
    fake_forecast[1].side_effect = forecast_with({"rre150h0": {4: 0.4}, "rp0003i0": {8: 60.0}})
    await setup_integration()
    assert state(hass, "laundry_weather") == "off"
    laundry = attributes(hass, "laundry_weather")
    assert laundry["dry_hours"] == 3
    assert (laundry["window_start"], laundry["window_end"]) == ("2026-11-08T11:00:00+01:00", "2026-11-08T14:00:00+01:00")


async def test_laundry_does_not_dry_in_the_cold_or_at_night(hass: HomeAssistant, setup_integration, fake_forecast, freezer) -> None:
    fake_forecast[1].side_effect = forecast_with({"tre200h0": dict.fromkeys(range(1, 8), 2.0)})
    await setup_integration()
    # too cold until 18:00, then only two hours are left
    assert attributes(hass, "laundry_weather")["dry_hours"] == 2
    assert state(hass, "laundry_weather") == "off"


async def test_frozen_windscreen_tomorrow_morning(hass: HomeAssistant, setup_integration, fake_forecast) -> None:
    # 0.5 °C at 06:00 tomorrow; the frost at 10:00 is after the drive to work
    fake_forecast[1].side_effect = forecast_with({"tre200h0": {20: 0.5, 24: -5.0}})
    await setup_integration()
    assert state(hass, "frozen_windscreen") == "on"
    windscreen = attributes(hass, "frozen_windscreen")
    assert windscreen["threshold"] == 1.0
    assert (windscreen["morning_minimum"], windscreen["morning_minimum_at"]) == (0.5, "2026-11-09T06:00:00+01:00")
    # no frost tonight by the frost sensor's own rule (0 °C before 09:00)
    assert state(hass, "frost_tonight") == "off"
    # the frost trigger picks its entity by the class "cold": only the frost sensor has it
    assert "device_class" not in windscreen
    assert attributes(hass, "frost_tonight")["device_class"] == "cold"


async def test_hot_day_cool_night_and_watering(hass: HomeAssistant, setup_integration, fake_forecast) -> None:
    fake_forecast[1].side_effect = forecast_with({"tre200px": {0: 28.0}})
    entry = await setup_integration()
    assert state(hass, "cool_night") == "on"
    night = attributes(hass, "cool_night")
    assert (night["today_high"], night["night_minimum"]) == (28.0, 5.0)
    assert state(hass, "watering_needed") == "on"

    # a warm night, and rain tomorrow
    forecast = entry.runtime_data.forecast
    forecast.data.hourly["tre200h0"] = [(ts, 21.0) for ts, _value in forecast.data.hourly["tre200h0"]]
    forecast.data.hourly["rre150h0"][30] = (forecast.data.hourly["rre150h0"][30][0], 3.5)
    forecast.async_update_listeners()
    await hass.async_block_till_done()
    assert state(hass, "cool_night") == "off"
    assert state(hass, "watering_needed") == "off"
    assert attributes(hass, "watering_needed")["precipitation_next_48h"] == 3.5


async def test_no_everyday_sensors_without_the_hourly_forecast(hass: HomeAssistant, setup_integration) -> None:
    await setup_integration(hourly=False)
    for key in ("laundry_weather", "frozen_windscreen", "cool_night", "watering_needed"):
        assert hass.states.get(entity("binary_sensor", key)) is None


async def test_hours_without_values(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_integration()
    forecast = entry.runtime_data.forecast
    forecast.data.hourly["tre200h0"] = [(ts, None) for ts, _value in forecast.data.hourly["tre200h0"]]
    forecast.data.hourly["rre150h0"] = []
    forecast.async_update_listeners()
    await hass.async_block_till_done()
    assert state(hass, "laundry_weather") == "off"
    assert attributes(hass, "laundry_weather")["window_start"] is None
    assert state(hass, "frozen_windscreen") == "off"
    assert attributes(hass, "frozen_windscreen")["morning_minimum"] is None
    assert state(hass, "watering_needed") == "off"


# --- from the station ----------------------------------------------------------


def test_what_the_air_feels_like() -> None:
    assert apparent_temperature(20.0, 50.0, 0.0) == 19.8
    assert apparent_temperature(20.0, 50.0, 18.0) == 16.3  # wind cools
    assert apparent_temperature(30.0, 70.0, 5.0) > 30.0  # humid heat feels hotter
    assert apparent_temperature(-5.0, 80.0, 30.0) < -10.0
    for missing in ((None, 50.0, 0.0), (20.0, None, 0.0), (20.0, 50.0, None)):
        assert apparent_temperature(*missing) is None


def test_pressure_trend_over_three_hours() -> None:
    assert pressure_trend({"pp0qffs0": 1010.0}, {"pp0qffs0": 1008.5}) == (1.5, "rising")
    assert pressure_trend({"pp0qffs0": 1005.0}, {"pp0qffs0": 1008.2}) == (-3.2, "falling_fast")
    assert pressure_trend({"pp0qffs0": 1012.0}, {"pp0qffs0": 1008.5}) == (3.5, "rising_fast")
    assert pressure_trend({"pp0qffs0": 1008.9}, {"pp0qffs0": 1008.5}) == (0.4, "steady")
    assert pressure_trend({"pp0qffs0": 1007.0}, {"pp0qffs0": 1008.5}) == (-1.5, "falling")
    # the first pressure both rows have
    assert pressure_trend({"pp0qffs0": None, "pp0qnhs0": 1020.0}, {"pp0qnhs0": 1019.0}) == (1.0, "rising")
    assert pressure_trend({"prestas0": 950.0}, {"prestas0": 950.0}) == (0.0, "steady")
    assert pressure_trend({"pp0qffs0": 1010.0}, None) is None
    assert pressure_trend({"pp0qffs0": 1010.0}, {"tre200s0": 5.0}) is None


async def test_station_sensors(hass: HomeAssistant, setup_integration) -> None:
    reading = station_reading()
    reading.earlier = {"pp0qnhs0": 1016.0}
    await setup_everything(hass, setup_integration, reading=reading)
    # 7.5 °C, 74 %, 9.4 km/h
    assert state(hass, "apparent_temperature", "sensor") == "4.2"
    assert state(hass, "pressure_trend", "sensor") == "2.2"
    assert attributes(hass, "pressure_trend", "sensor")["tendency"] == "rising"
    assert attributes(hass, "pressure_trend", "sensor")["hours"] == 3


async def test_station_sensors_without_what_they_need(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, reading=station_reading(ure200s0=None))
    assert state(hass, "apparent_temperature", "sensor") == "unknown"
    assert state(hass, "pressure_trend", "sensor") == "unknown"  # no row three hours back
    assert attributes(hass, "pressure_trend", "sensor")["tendency"] is None


async def test_station_sensors_go_with_the_station(hass: HomeAssistant, setup_integration) -> None:
    await setup_integration()
    assert hass.states.get(entity("sensor", "apparent_temperature")) is None
    assert hass.states.get(entity("sensor", "pressure_trend")) is None


async def test_the_row_three_hours_earlier_comes_from_the_file() -> None:
    body = (
        "station_abbr;reference_timestamp;tre200s0;pp0qffs0\n"
        "BER;08.11.2026 07:10;4.0;1010.0\n"
        "BER;08.11.2026 07:20;4.1;1011.0\n"
        "BER;08.11.2026 10:10;6.0;1013.0\n"
        "BER;08.11.2026 10:20;6.1;1013.5\n"
    ).encode("latin-1")
    reading = await async_fetch_station_reading(FakeSession({station_now_url("BER"): body}), "BER")
    assert reading.values["pp0qffs0"] == 1013.5
    assert reading.earlier == {"tre200s0": 4.1, "pp0qffs0": 1011.0}
    # shortly after midnight UTC the file does not reach three hours back
    short = b"\n".join(body.split(b"\n")[:1] + body.split(b"\n")[3:])
    assert (await async_fetch_station_reading(FakeSession({station_now_url("BER"): short}), "BER")).earlier is None


async def test_after_midnight_the_earlier_row_is_remembered(hass: HomeAssistant, swiss_now, freezer) -> None:
    coordinator = StationCoordinator(hass, make_entry(hass, {"station": "SMA"}))
    start = NOW - timedelta(minutes=10)
    readings = [
        StationReading(abbr="SMA", timestamp=start, values={"pp0qffs0": 1000.0}),
        StationReading(abbr="SMA", timestamp=start + timedelta(hours=1), values={"pp0qffs0": 1001.0}),
        StationReading(abbr="SMA", timestamp=start + timedelta(hours=3), values={"pp0qffs0": 1004.0}),
        StationReading(abbr="SMA", timestamp=start + timedelta(hours=7), values={"pp0qffs0": 1004.0}),
    ]
    seen = []
    for reading in readings:
        freezer.move_to(reading.timestamp + timedelta(minutes=10))
        with patch(READING, return_value=reading):
            await coordinator.async_refresh()
        seen.append(coordinator.data.earlier)
    # nothing to compare with at first, then the row read three hours before
    assert seen == [None, None, {"pp0qffs0": 1000.0}, None]
    assert pressure_trend(readings[2].values, readings[2].earlier) == (4.0, "rising_fast")
    # a row the file itself supplies is kept as it is
    own = StationReading(abbr="SMA", timestamp=start + timedelta(hours=8), values={"pp0qffs0": 1005.0}, earlier={"pp0qffs0": 990.0})
    with patch(READING, return_value=own):
        await coordinator.async_refresh()
    assert coordinator.data.earlier == {"pp0qffs0": 990.0}
