"""Unit tests of the forecast and derived-value helpers, on a hand-made
snapshot so no model run is needed."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from freezegun import freeze_time

from custom_components.swiss_meteo.coordinator import ForecastSnapshot
from custom_components.swiss_meteo.derived import (
    day_mean,
    heating_degree_days,
    max_gust,
    next_rain,
    window_sum,
)
from custom_components.swiss_meteo.forecast import (
    hour_floor,
    hourly_forecast,
    next_hours,
    value_at,
)

NOW = datetime(2026, 11, 8, 10, 30, tzinfo=UTC)
HOUR = NOW.replace(minute=0)


def _hourly(values: list[float | None], start: datetime = HOUR) -> list[tuple[datetime, float | None]]:
    return [(start + timedelta(hours=i), v) for i, v in enumerate(values)]


def test_value_at_takes_latest_value_at_or_before() -> None:
    series = _hourly([1.0, 2.0, 3.0])
    assert value_at(series, HOUR + timedelta(minutes=30)) == 1.0
    assert value_at(series, HOUR + timedelta(hours=2)) == 3.0
    # before the series: the first value
    assert value_at(series, HOUR - timedelta(hours=5)) == 1.0
    assert value_at(None, HOUR) is None


def test_hour_floor() -> None:
    assert hour_floor(NOW) == HOUR


@freeze_time(NOW)
def test_hourly_forecast_starts_at_current_hour_and_limits_hours() -> None:
    snap = ForecastSnapshot(
        hourly={
            "tre200h0": _hourly([5.0, 6.0, 7.0, 8.0], start=HOUR - timedelta(hours=1)),
            "jww003i0": _hourly([1, 1, 128, 128], start=HOUR - timedelta(hours=1)),
            "rre150h0": _hourly([0.0, 0.0, 0.4, 1.2], start=HOUR - timedelta(hours=1)),
        }
    )
    entries = hourly_forecast(snap, hours=2)
    assert len(entries) == 2
    assert entries[0]["native_temperature"] == 6.0  # the hour before now is dropped
    assert entries[1]["condition"] == "fog"  # symbol 128
    assert entries[1]["native_precipitation"] == 0.4


@freeze_time(NOW)
def test_next_hours_and_next_rain() -> None:
    snap = ForecastSnapshot(hourly={"rre150h0": _hourly([0.0, 0.05, 0.3, 2.0])})
    coming = next_hours(snap, 3)
    assert [v for _ts, v in coming] == [0.0, 0.05, 0.3]
    when, amount = next_rain(snap)
    assert when == HOUR + timedelta(hours=2)
    assert amount == 0.3
    assert next_rain(ForecastSnapshot()) is None


@freeze_time(NOW)
def test_window_sum_and_max_gust() -> None:
    snap = ForecastSnapshot(hourly={"fu3010h1": _hourly([20.0, 55.0, 40.0, 90.0, 10.0, 10.0, 99.0])})
    assert window_sum(snap.hourly["fu3010h1"], 3) == 115.0
    when, kmh = max_gust(snap, hours=6)
    assert kmh == 90.0
    assert when == HOUR + timedelta(hours=3)


def test_heating_degree_days_after_sia() -> None:
    assert heating_degree_days(None) is None
    assert heating_degree_days(15.0) == 0.0
    assert heating_degree_days(5.0) == 15.0


def test_day_mean_falls_back_to_high_and_low() -> None:
    day = datetime(2026, 11, 9, tzinfo=UTC)
    snap = ForecastSnapshot(
        daily={"tre200px": [(day, 10.0)], "tre200pn": [(day, 2.0)]},
    )
    assert day_mean(snap, day.date()) == 6.0
    assert day_mean(ForecastSnapshot(), day.date()) is None
