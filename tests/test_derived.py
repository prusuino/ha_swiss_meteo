"""The figures derived from a forecast run (night minimum, best window,
daily sums) and the daily forecast list, on hand-made snapshots."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from freezegun import freeze_time

from custom_components.swiss_meteo.coordinator import ForecastSnapshot
from custom_components.swiss_meteo.derived import (
    best_window,
    day_mean,
    day_sum,
    heating_degree_days,
    hours_covered,
    max_gust,
    next_rain,
    night_minimum,
    window_sum,
)
from custom_components.swiss_meteo.forecast import (
    cloud_coverage,
    daily_forecast,
    daily_values,
    day_from_hourly,
    hourly_forecast,
    local_date,
    next_hours,
)

NOW = datetime(2026, 11, 8, 10, 30, tzinfo=UTC)
HOUR = NOW.replace(minute=0)
TODAY = date(2026, 11, 8)
MIDNIGHT = datetime(2026, 11, 8, tzinfo=UTC)


def _hourly(values: list[float | None], start: datetime = HOUR) -> list[tuple[datetime, float | None]]:
    return [(start + timedelta(hours=i), v) for i, v in enumerate(values)]


def _daily(values: list[float | None], start: datetime = MIDNIGHT) -> list[tuple[datetime, float | None]]:
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


WINDOW_SNAPSHOT = ForecastSnapshot(
    hourly={
        "rre150h0": _hourly([1.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 2.0]),
        "sre000h0": _hourly([0.0, 60.0, 60.0, 0.0, 30.0, 30.0, 30.0, 0.0]),
        "fu3010h1": _hourly([30.0, 20.0, 25.0, 40.0, 15.0, 12.0, 8.0, 5.0]),
        "tre200h0": _hourly([5.0, 6.0, None, 8.0, 9.0, 10.0, 11.0, 12.0]),
    }
)


def test_nothing_to_derive_from_an_empty_snapshot() -> None:
    empty = ForecastSnapshot()
    assert day_mean(empty, TODAY) is None
    assert heating_degree_days(None) is None
    assert day_sum(empty, "gre000h0", TODAY) is None
    assert hours_covered(empty, TODAY) == 0
    assert window_sum(None, 24) is None
    assert next_rain(empty) is None
    assert night_minimum(empty) is None
    assert max_gust(empty) is None
    assert best_window(empty, 3, 24, "dry") is None
    assert daily_forecast(empty) == []
    assert hourly_forecast(empty) == []
    assert next_hours(empty, 6) == []
    assert cloud_coverage(empty, HOUR) is None
    assert day_from_hourly(None, TODAY, max) is None


def test_day_sum_and_hours_covered_count_the_local_day_only() -> None:
    # 22 hours from 20:00 the evening before: 4 of yesterday, 18 of today
    start = MIDNIGHT - timedelta(hours=4)
    snap = ForecastSnapshot(
        hourly={
            "tre200h0": _hourly([4.0] * 21 + [None], start=start),
            "gre000h0": _hourly([100.0] * 22, start=start),
        }
    )
    assert hours_covered(snap, TODAY) == 17  # the hour without a value does not count
    assert hours_covered(snap, TODAY - timedelta(days=1)) == 4
    assert day_sum(snap, "gre000h0", TODAY) == 1800.0
    assert day_sum(snap, "gre000h0", TODAY + timedelta(days=1)) is None
    assert day_sum(snap, "sre000h0", TODAY) is None


@freeze_time(NOW)
def test_window_sum_without_a_value_in_the_window() -> None:
    assert window_sum(_hourly([None, None]), 24) is None
    assert window_sum(_hourly([1.0, 2.0], start=HOUR - timedelta(hours=5)), 2) is None


@freeze_time(NOW)
def test_night_minimum_runs_until_nine_the_next_morning() -> None:
    # from 08:00 UTC today: one value an hour, the lowest at 05:00 tomorrow
    values = [9.0, 8.0, 7.0] + [6.0] * 18 + [-2.0] + [3.0] * 4 + [-5.0, -6.0]
    snap = ForecastSnapshot(hourly={"tre200h0": _hourly(values, start=HOUR - timedelta(hours=2))})
    when, low = night_minimum(snap)
    # the colder hours after 09:00 tomorrow belong to the next day
    assert low == -2.0
    assert when == datetime(2026, 11, 9, 5, 0, tzinfo=UTC)


@freeze_time(datetime(2026, 11, 8, 3, 30, tzinfo=UTC))
def test_night_minimum_before_nine_ends_the_same_morning() -> None:
    start = datetime(2026, 11, 8, 1, 0, tzinfo=UTC)
    # 01:00 is past, 03:00 to 09:00 count, the hours after do not
    values = [-9.0, None, 2.0, 1.0, 0.5, 1.5, 2.0, 3.0, 4.0, 5.0, -3.0]
    snap = ForecastSnapshot(hourly={"tre200h0": _hourly(values, start=start)})
    assert night_minimum(snap) == (datetime(2026, 11, 8, 5, 0, tzinfo=UTC), 0.5)


@freeze_time(NOW)
def test_night_minimum_without_a_coming_value() -> None:
    snap = ForecastSnapshot(hourly={"tre200h0": _hourly([1.0, 2.0], start=HOUR - timedelta(hours=6))})
    assert night_minimum(snap) is None


@freeze_time(NOW)
def test_best_window_by_criterion() -> None:
    dry = best_window(WINDOW_SNAPSHOT, 2, 24, "dry")
    assert dry == {
        "found": True,
        "start": (HOUR + timedelta(hours=5)).isoformat(),
        "end": (HOUR + timedelta(hours=7)).isoformat(),
        "precipitation_mm": 0.0,
        "sunshine_h": 1.0,
        "max_gust_kmh": 12,
        "mean_temperature": 10.5,
        "criterion": "dry",
    }

    sunny = best_window(WINDOW_SNAPSHOT, 2, 24, "sunny")
    assert sunny["start"] == (HOUR + timedelta(hours=1)).isoformat()
    assert sunny["sunshine_h"] == 2.0
    assert sunny["max_gust_kmh"] == 25
    assert sunny["mean_temperature"] == 6.0  # the hour without a temperature is left out

    calm = best_window(WINDOW_SNAPSHOT, 2, 24, "calm")
    assert calm["start"] == (HOUR + timedelta(hours=6)).isoformat()
    assert calm["precipitation_mm"] == 2.0
    assert calm["sunshine_h"] == 0.5
    assert calm["max_gust_kmh"] == 8
    assert calm["criterion"] == "calm"


@freeze_time(NOW)
def test_best_window_respects_the_search_span_and_the_run_length() -> None:
    # only windows starting in the next three hours are looked at
    near = best_window(WINDOW_SNAPSHOT, 2, 3, "dry")
    assert near["start"] == (HOUR + timedelta(hours=1)).isoformat()
    # a window longer than the run is never complete
    assert best_window(WINDOW_SNAPSHOT, 12, 24, "dry") is None
    # equal windows: the earlier one wins; no temperatures, no mean
    flat = ForecastSnapshot(hourly={"rre150h0": _hourly([0.0] * 6)})
    first = best_window(flat, 3, 24, "dry")
    assert first["start"] == HOUR.isoformat()
    assert first["mean_temperature"] is None
    assert first["max_gust_kmh"] == 0


def test_daily_values_keep_the_calendar_day_of_the_stamp() -> None:
    snap = ForecastSnapshot(daily={"tre200px": _daily([10.0, 11.0])})
    assert local_date(MIDNIGHT) == TODAY
    assert daily_values(snap, "tre200px") == {TODAY: 10.0, TODAY + timedelta(days=1): 11.0}
    assert daily_values(snap, "tre200pn") == {}


@freeze_time(NOW)
def test_daily_forecast_from_daily_and_hourly_series() -> None:
    yesterday = MIDNIGHT - timedelta(days=1)
    snap = ForecastSnapshot(
        daily={
            "jp2000d0": _daily([4.0, 1.0, 120.0], start=yesterday),
            "tre200px": _daily([9.0, 10.0, 11.0], start=yesterday),
            "tre200pn": _daily([1.0, 2.0, 3.0], start=yesterday),
            "rka150p0": _daily([0.0, 0.4, None], start=yesterday),
            "rreq10p0": _daily([0.0, 0.0, 1.0], start=yesterday),
            "rreq90p0": _daily([0.0, 2.0, 9.0], start=yesterday),
        },
        hourly={
            "rp0003i0": _hourly([10.0, 40.0, 20.0]),
            "fu3010h0": _hourly([8.0, 12.0, 9.0]),
            "fu3010h1": _hourly([20.0, 35.0, 30.0]),
            "sre000h0": _hourly([30.0, 60.0, 15.0]),
        },
    )
    today, tomorrow = daily_forecast(snap)  # yesterday is dropped
    assert today == {
        "datetime": "2026-11-08T00:00:00+00:00",
        "condition": "sunny",
        "native_temperature": 10.0,
        "native_templow": 2.0,
        "native_precipitation": 0.4,
        "precipitation_probability": 40.0,
        "native_wind_speed": 12.0,
        "native_wind_gust_speed": 35.0,
        "symbol": 1,
        "precipitation_min": 0.0,
        "precipitation_max": 2.0,
        "sunshine_hours": 1.8,
    }
    # the night code of a daily symbol is read as its day counterpart;
    # what the run does not carry for that day is left out
    assert tomorrow == {
        "datetime": "2026-11-09T00:00:00+00:00",
        "condition": "pouring",
        "native_temperature": 11.0,
        "native_templow": 3.0,
        "symbol": 120,
        "precipitation_min": 1.0,
        "precipitation_max": 9.0,
    }


@freeze_time(NOW)
def test_daily_forecast_keeps_a_day_without_a_symbol() -> None:
    days = daily_forecast(ForecastSnapshot(daily={"tre200px": _daily([10.0])}))
    assert days == [{"datetime": "2026-11-08T00:00:00+00:00", "condition": None, "native_temperature": 10.0}]


def test_cloud_coverage_combines_the_three_layers() -> None:
    snap = ForecastSnapshot(
        hourly={
            "nprolohs": _hourly([0.5, 0.0, 1.4]),
            "npromths": _hourly([0.5, 0.0, 0.0]),
            "nprohihs": _hourly([0.0, -0.2, 0.0]),
        }
    )
    assert cloud_coverage(snap, HOUR) == 75
    assert cloud_coverage(snap, HOUR + timedelta(hours=1)) == 0  # below zero counts as clear
    assert cloud_coverage(snap, HOUR + timedelta(hours=2)) == 100  # above one counts as covered
    # one layer missing: no figure
    del snap.hourly["nprohihs"]
    assert cloud_coverage(snap, HOUR) is None


@freeze_time(NOW)
def test_hourly_forecast_carries_the_cloud_cover() -> None:
    snap = ForecastSnapshot(
        hourly={
            "tre200h0": _hourly([5.0]),
            "nprolohs": _hourly([0.2]),
            "npromths": _hourly([0.0]),
            "nprohihs": _hourly([0.0]),
        }
    )
    (entry,) = hourly_forecast(snap)
    assert entry["cloud_coverage"] == 20
    assert entry["condition"] is None
    assert "native_precipitation" not in entry
