"""The sensors as Home Assistant shows them: station values, the day's
figures from the forecast, pollen, warnings, radar and the diagnostics."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.swiss_meteo.coordinator import ForecastCoordinator, PrecipCoordinator, StationCoordinator
from custom_components.swiss_meteo.meteoalarm import WARNINGS_URL, WarningsCoordinator
from custom_components.swiss_meteo.open_meteo import OpenMeteoCoordinator
from custom_components.swiss_meteo.pollen import PollenCoordinator
from custom_components.swiss_meteo.radar import RadarCoordinator
from custom_components.swiss_meteo.sensor import (
    AirQualityLevelSensor,
    DayValueSensor,
    DerivedSensor,
    ForecastRunSensor,
    OpenMeteoSensor,
    PollenForecastSensor,
    PollenLevelSensor,
    PollenSensor,
    PrecipSensor,
    RadarDistanceSensor,
    RadarEtaSensor,
    RadarRateSensor,
    StationSensor,
    StationTimeSensor,
    TrafficSensor,
    UvIndexMaxSensor,
    WarningLevelSensor,
)

from .conftest import NOW, RUN, find_device, make_entry
from .fakes import FakeResponse
from .feeds import EVERYTHING, entity, forecast_with, precip_reading, setup_everything, station_reading


def state(hass: HomeAssistant, key: str) -> str:
    return hass.states.get(entity("sensor", key)).state


def attributes(hass: HomeAssistant, key: str) -> dict:
    return dict(hass.states.get(entity("sensor", key)).attributes)


# --- station -----------------------------------------------------------------


async def test_station_values(hass: HomeAssistant, setup_integration, all_entities_enabled) -> None:
    await setup_everything(hass, setup_integration)
    measured = {
        "temperature": "7.5",
        "dew_point": "3.1",
        "humidity": "74.0",
        "pressure_qnh": "1018.2",
        "wind_speed": "9.4",
        "wind_gust": "22.3",
        "wind_direction": "250.0",
        "precipitation": "0.2",
        "sunshine": "4.0",
        "global_radiation": "180.0",
        "snow_depth": "0.0",
    }
    for key, value in measured.items():
        assert state(hass, key) == value, key
    # a column the station does not deliver stays unknown
    assert state(hass, "soil_temperature_5cm") == "unknown"
    assert state(hass, "foehn_index") == "unknown"

    assert state(hass, "station_time") == "2026-11-08T10:20:00+00:00"
    assert attributes(hass, "station_time")["station"] == "SMA"
    assert attributes(hass, "station_time")["fresh"] is True


async def test_rare_station_columns_are_off_by_default(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    registry = er.async_get(hass)
    assert state(hass, "temperature") == "7.5"
    for key in ("pressure_station", "soil_temperature_10cm", "geopotential_850", "snow_depth"):
        assert hass.states.get(entity("sensor", key)) is None, key
        assert registry.async_get(entity("sensor", key)).disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_old_station_values_are_not_shown(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, reading=station_reading(minutes_old=50))
    assert state(hass, "temperature") == "unavailable"
    assert state(hass, "humidity") == "unavailable"
    # the time of the reading stays visible and says why
    assert state(hass, "station_time") == "2026-11-08T09:40:00+00:00"
    assert attributes(hass, "station_time")["fresh"] is False


async def test_no_station_no_station_sensors(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, station="")
    assert hass.states.get(entity("sensor", "temperature")) is None
    assert hass.states.get(entity("sensor", "station_time")) is None
    assert state(hass, "today_max") == "10.0"


# --- precipitation station ---------------------------------------------------


async def test_precipitation_from_its_own_station(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_everything(hass, setup_integration, precip_station="WAG", precip_station_name="Waldegg")
    # the gauge's value, not the 0.2 mm of the weather station ...
    assert state(hass, "precipitation") == "1.4"
    assert attributes(hass, "precipitation")["station"] == "WAG"
    assert attributes(hass, "precipitation")["station_name"] == "Waldegg"
    # ... under the id the weather station's value had
    registered = er.async_get(hass).async_get_entity_id("sensor", entry.domain, f"{entry.entry_id}_precipitation")
    assert registered == entity("sensor", "precipitation")
    # everything else still comes from the weather station
    assert state(hass, "temperature") == "7.5"
    assert attributes(hass, "station_time")["station"] == "SMA"
    # the device says where the rain is measured
    assert "precipitation Waldegg" in find_device(hass, entry.entry_id).model


async def test_old_precipitation_is_not_shown(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, precip=precip_reading(minutes_old=50), precip_station="WAG")
    assert state(hass, "precipitation") == "unavailable"
    assert state(hass, "temperature") == "7.5"


async def test_precipitation_station_without_a_weather_station(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, station="", precip_station="WAG")
    assert state(hass, "precipitation") == "1.4"
    # without a name the abbreviation stands in
    assert attributes(hass, "precipitation")["station_name"] == "WAG"
    assert hass.states.get(entity("sensor", "temperature")) is None
    assert hass.states.get(entity("sensor", "station_time")) is None


async def test_precipitation_sensor_before_the_first_read(hass: HomeAssistant, swiss_now) -> None:
    entry = make_entry(hass, {**EVERYTHING, "precip_station": "WAG", "precip_station_name": "Waldegg"})
    sensor = PrecipSensor(hass, entry, PrecipCoordinator(hass, entry))
    assert sensor.native_value is None
    assert sensor.available is False
    assert sensor.extra_state_attributes == {"station": "WAG", "station_name": "Waldegg"}


# --- forecast ----------------------------------------------------------------


async def test_day_values(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    assert state(hass, "today_max") == "10.0"
    assert state(hass, "today_min") == "2.0"
    assert state(hass, "today_precipitation") == "0.0"
    assert state(hass, "tomorrow_max") == "11.0"
    assert state(hass, "tomorrow_min") == "3.0"
    assert state(hass, "tomorrow_precipitation") == "1.0"


async def test_derived_figures(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    # today has fewer than 20 hours left in the run: mean of high and low
    assert state(hass, "today_mean") == "6.0"
    assert attributes(hass, "today_mean")["hours_in_forecast"] == 14
    # tomorrow is covered hour by hour
    assert state(hass, "tomorrow_mean") == "5.0"
    assert attributes(hass, "tomorrow_mean")["hours_in_forecast"] == 24

    assert state(hass, "heating_degree_days_today") == "14.0"
    today = attributes(hass, "heating_degree_days_today")
    assert (today["threshold"], today["base"], today["mean_temperature"]) == (12.0, 20.0, 6.0)
    assert state(hass, "heating_degree_days_tomorrow") == "15.0"
    assert attributes(hass, "heating_degree_days_tomorrow")["mean_temperature"] == 5.0

    assert state(hass, "radiation_today") == "2.1"
    assert attributes(hass, "radiation_today")["hours_in_forecast"] == 14
    assert state(hass, "radiation_tomorrow") == "3.6"
    assert attributes(hass, "radiation_tomorrow")["hours_in_forecast"] == 24
    assert state(hass, "sunshine_today") == "7.0"
    assert state(hass, "sunshine_tomorrow") == "12.0"

    assert state(hass, "precipitation_next_24h") == "0.0"
    assert state(hass, "next_rain") == "unknown"
    assert "precipitation_mm" not in attributes(hass, "next_rain")


async def test_next_rain(hass: HomeAssistant, setup_integration, fake_forecast) -> None:
    fake_forecast[1].side_effect = forecast_with({"rre150h0": {5: 1.2, 9: 0.4}})
    await setup_everything(hass, setup_integration)
    assert state(hass, "next_rain") == (RUN + timedelta(hours=5)).isoformat()
    rain = attributes(hass, "next_rain")
    assert rain["precipitation_mm"] == 1.2
    assert rain["hours_until"] in (3, 4)  # three and a half hours from now
    assert state(hass, "precipitation_next_24h") == "1.6"


async def test_daily_files_alone(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, hourly=False)
    # the means come from high and low, the hourly figures do not exist
    assert state(hass, "today_mean") == "6.0"
    assert state(hass, "tomorrow_mean") == "7.0"
    assert state(hass, "heating_degree_days_today") == "14.0"
    assert state(hass, "heating_degree_days_tomorrow") == "13.0"
    for key in ("radiation_today", "sunshine_tomorrow", "precipitation_next_24h", "next_rain"):
        assert hass.states.get(entity("sensor", key)) is None, key
    assert attributes(hass, "forecast_run")["parameters_hourly"] == []


async def test_forecast_run_and_traffic(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    assert state(hass, "forecast_run") == RUN.isoformat()
    run = attributes(hass, "forecast_run")
    assert run["daily_fetched"] == NOW.isoformat()
    assert run["hourly_fetched"] == NOW.isoformat()
    assert run["parameters_daily"] == ["jp2000d0", "rka150p0", "rreq10p0", "rreq90p0", "tre200pn", "tre200px"]
    assert "tre200h0" in run["parameters_hourly"]
    assert run["missing"] == []

    traffic = attributes(hass, "traffic_today")
    assert float(state(hass, "traffic_today")) > 0
    assert traffic["requests_today"] > 15  # the forecast files and the radar frames
    assert traffic["last_read_requests"] >= 1


# --- pollen ------------------------------------------------------------------


async def test_pollen(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    assert state(hass, "pollen_birch") == "30.0"
    birch = attributes(hass, "pollen_birch")
    assert birch["station"] == "PZH"
    assert birch["measured"] == "2026-11-08T09:00:00+00:00"
    assert (birch["daily_mean"], birch["hours_today"], birch["level"]) == (20.0, 3, "moderate")
    assert state(hass, "pollen_grasses") == "2.0"
    assert attributes(hass, "pollen_grasses")["level"] == "low"
    # nothing measured for the species today
    assert state(hass, "pollen_oak") == "unknown"
    assert attributes(hass, "pollen_oak")["level"] is None

    assert state(hass, "pollen_level") == "moderate"
    level = attributes(hass, "pollen_level")
    assert level["options"] == ["none", "low", "moderate", "high", "very_high"]
    assert (level["birch"], level["grasses"], level["hazel"]) == ("moderate", "low", None)
    assert level["highest"] == ["birch"]


async def test_no_pollen_station_no_pollen_sensors(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, pollen_station="")
    assert hass.states.get(entity("sensor", "pollen_birch")) is None
    assert hass.states.get(entity("sensor", "pollen_level")) is None


# --- warnings ----------------------------------------------------------------


async def test_warning_level(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    assert state(hass, "warning_level") == "yellow"
    level = attributes(hass, "warning_level")
    assert level["icon"] == "mdi:alert"
    assert level["options"] == ["none", "yellow", "orange", "red"]
    assert (level["count"], level["upcoming"], level["highest_upcoming"]) == (1, 1, "red")
    assert level["next_onset"] == "2026-11-08T18:00:00+00:00"
    assert level["feed_alerts"] == 2
    assert level["fetched"] == NOW.isoformat()
    first = level["warnings"][0]
    assert first["headline"] == "Strong wind"
    assert first["description"] == "Gusts up to 90 km/h."
    assert first["instruction"] == "Secure loose objects."


async def test_no_warning(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, routes={WARNINGS_URL: FakeResponse(payload={"warnings": []})})
    assert state(hass, "warning_level") == "none"
    level = attributes(hass, "warning_level")
    assert level["icon"] == "mdi:alert-outline"
    assert (level["count"], level["upcoming"], level["highest_upcoming"], level["next_onset"]) == (0, 0, "none", None)
    assert level["warnings"] == []


async def test_warnings_switched_off(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, warnings=False)
    assert hass.states.get(entity("sensor", "warning_level")) is None


# --- radar -------------------------------------------------------------------


async def test_radar(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    assert state(hass, "radar_rain_rate") == "1.5"
    rate = attributes(hass, "radar_rain_rate")
    assert rate["radar_time"] == "2026-11-08T10:25:00+00:00"
    assert rate["rate_at_point"] == 1.5
    assert rate["rain_cells_in_window"] == 1
    assert "not an official nowcast" in rate["estimate"]

    assert state(hass, "radar_rain_distance") == "0.0"
    distance = attributes(hass, "radar_rain_distance")
    assert (distance["bearing"], distance["search_radius_km"]) == (0, 60)

    assert state(hass, "radar_rain_eta") == "0"
    eta = attributes(hass, "radar_rain_eta")
    assert (eta["speed_kmh"], eta["direction"]) == (None, None)


async def test_radar_switched_off(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration, radar=False)
    assert hass.states.get(entity("sensor", "radar_rain_rate")) is None


# --- before the first read ---------------------------------------------------


async def test_nothing_read_yet(hass: HomeAssistant, swiss_now) -> None:
    """The entities answer without data: no value, no attributes."""
    entry = make_entry(hass, EVERYTHING)
    forecast = ForecastCoordinator(hass, entry)
    station = StationCoordinator(hass, entry)
    pollen = PollenCoordinator(hass, entry)
    warnings = WarningsCoordinator(hass, entry)
    radar = RadarCoordinator(hass, entry)
    open_meteo = OpenMeteoCoordinator(hass, entry)

    empty = [
        StationSensor(hass, entry, station, "tre200s0", "temperature"),
        DayValueSensor(hass, entry, forecast, "today", "max"),
        DerivedSensor(hass, entry, forecast, "today_mean"),
        PollenSensor(hass, entry, pollen, "birch"),
        PollenLevelSensor(hass, entry, pollen),
        OpenMeteoSensor(hass, entry, open_meteo, "pm10"),
        AirQualityLevelSensor(hass, entry, open_meteo),
        UvIndexMaxSensor(hass, entry, open_meteo),
        PollenForecastSensor(hass, entry, open_meteo, "birch"),
        WarningLevelSensor(hass, entry, warnings),
        RadarRateSensor(hass, entry, radar),
        RadarDistanceSensor(hass, entry, radar),
        RadarEtaSensor(hass, entry, radar),
        ForecastRunSensor(hass, entry, forecast),
        TrafficSensor(hass, entry, forecast),
    ]
    for sensor in empty:
        assert sensor.native_value is None, sensor.entity_id
        assert not sensor.extra_state_attributes, sensor.entity_id

    time = StationTimeSensor(hass, entry, station)
    assert time.native_value is None
    assert time.extra_state_attributes == {"station": "SMA", "fresh": False}
    assert WarningLevelSensor(hass, entry, warnings).icon == "mdi:alert-outline"
    # what was read once is not shown as current before the first answer
    assert StationSensor(hass, entry, station, "tre200s0", "temperature").available is False
    assert RadarRateSensor(hass, entry, radar).available is False


async def test_a_key_without_a_figure(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_everything(hass, setup_integration)
    sensor = DerivedSensor(hass, entry, entry.runtime_data.forecast, "today_mean")
    sensor._key = "something_else"
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}
