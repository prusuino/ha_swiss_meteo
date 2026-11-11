"""The import of a station's archive into the long-term statistics: which
files are read, how their rows become statistics, and the whole import
against files served from memory."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.swiss_meteo.const import DOMAIN
from custom_components.swiss_meteo.history import (
    GROUPS,
    MEASUREMENTS,
    TOTALS,
    HistoryError,
    _fetch,
    _files,
    _measurement_stats,
    _parse,
    _prepare,
    _total_stats,
    _unit_class,
    async_import_history,
)

from .conftest import ENTRY_ID, NOW
from .fakes import FakeResponse, FakeSession

SESSION = "homeassistant.helpers.aiohttp_client.async_get_clientsession"
HISTORY = "custom_components.swiss_meteo.history"

DAILY_RECENT, DAILY_HISTORICAL = _files("BER", "daily", 2, NOW)
HOURLY_DECADE, HOURLY_RECENT = _files("BER", "hourly", 1, NOW)

PRECIPITATION = f"{DOMAIN}:station_ber_precipitation"
SUNSHINE = f"{DOMAIN}:station_ber_sunshine"
DEGREE_DAYS = f"{DOMAIN}:station_ber_heating_degree_days"
EVAPORATION = f"{DOMAIN}:station_ber_evaporation"

DAILY_HEADER = "station_abbr;reference_timestamp;tre200d0;tre200dn;tre200dx;ure200d0;fu3010d1;rka150d0;sre000d0;xno000d0\n"
RECENT_DAYS = (
    DAILY_HEADER
    + "BER;06.11.2026 00:00;5.0;1.0;9.0;80;40;2.5;120;14.0\n"
    + "BER;07.11.2026 00:00;6.0;2.0;10.0;;55;0.0;-;13.0\n"
).encode("latin-1")
OLDER_DAYS = (
    DAILY_HEADER
    + "BER;31.12.2024 00:00;0.0;0.0;0.0;70;10;9.9;10;20.0\n"
    + "BER;05.11.2026 00:00;4.0;0.0;8.0;85;30;1.0;60;15.0\n"
    + "BER;06.11.2026 00:00;5.0;1.0;9.0;80;40;2.5;120;14.0\n"
).encode("latin-1")
HOURS = (
    "station_abbr;reference_timestamp;tre200h0;tre200hn;tre200hx;rre150h0\n"
    "BER;08.11.2026 09:00;5.0;4.5;5.5;0.2\n"
    "BER;08.11.2026 10:00;6.0;5.5;;0.0\n"
).encode("latin-1")


def day(number: int, hour: int = 0) -> datetime:
    return datetime(2026, 11, number, hour, tzinfo=UTC)


def names(resolution: str, years: int, now: datetime = NOW) -> list[str]:
    return [url.rsplit("/", 1)[-1] for url in _files("BER", resolution, years, now)]


# --- the pieces --------------------------------------------------------------


def test_archive_files_for_the_requested_years() -> None:
    assert names("daily", 1) == ["ogd-smn_ber_d_recent.csv"]
    assert names("daily", 5) == ["ogd-smn_ber_d_recent.csv", "ogd-smn_ber_d_historical.csv"]
    assert names("hourly", 1) == ["ogd-smn_ber_h_historical_2020-2029.csv", "ogd-smn_ber_h_recent.csv"]
    assert names("hourly", 30) == [
        "ogd-smn_ber_h_historical_1990-1999.csv",
        "ogd-smn_ber_h_historical_2000-2009.csv",
        "ogd-smn_ber_h_historical_2010-2019.csv",
        "ogd-smn_ber_h_historical_2020-2029.csv",
        "ogd-smn_ber_h_recent.csv",
    ]
    # in the first year of a decade the recent file holds everything
    assert names("hourly", 1, datetime(2030, 3, 1, tzinfo=UTC)) == ["ogd-smn_ber_h_recent.csv"]
    assert DAILY_RECENT.startswith("https://") and "/ber/" in DAILY_RECENT


def test_groups_cover_every_series() -> None:
    assert {group for group, _hourly, _daily in MEASUREMENTS.values()} | {total[0] for total in TOTALS.values()} == set(GROUPS)


def test_unit_class_of_a_unit() -> None:
    assert _unit_class("°C") == "temperature"
    assert _unit_class("K·d") is None


async def test_fetch_answers() -> None:
    session = FakeSession({"https://host/ok.csv": b"data", "https://host/busy.csv": FakeResponse(503), "https://host/down.csv": aiohttp.ClientError("connection lost")})
    assert await _fetch(session, "https://host/ok.csv") == (b"data", 1)
    # a file the station does not have is simply empty
    assert await _fetch(session, "https://host/missing.csv") == (b"", 1)
    with pytest.raises(HistoryError, match="busy.csv: HTTP 503"):
        await _fetch(session, "https://host/busy.csv")
    with pytest.raises(HistoryError, match="down.csv: connection lost"):
        await _fetch(session, "https://host/down.csv")
    assert session.calls[0][2]["User-Agent"].startswith("SwissMeteo/")


def test_parse_keeps_the_rows_since_the_start() -> None:
    raw = (
        "station_abbr;reference_timestamp;tre200h0;rre150h0;remark\n"
        "BER;01.01.2026 00:00;1.0;0.0;x\n"
        "BER;01.01.2026 01:00;2.0;-;x\n"
        "BER\n"
        "\n"
        "BER;yesterday;3.0;1.0;x\n"
        "BER;01.01.2026 02:00;;0.4;x\n"
    ).encode("latin-1")
    since = datetime(2026, 1, 1, tzinfo=UTC)
    # hourly values are stamped at the end of their hour: the first row belongs to last year
    assert _parse(raw, since, 1) == [
        {"start": datetime(2026, 1, 1, 0, tzinfo=UTC), "tre200h0": 2.0},
        {"start": datetime(2026, 1, 1, 1, tzinfo=UTC), "rre150h0": 0.4},
    ]
    assert [row["start"].hour for row in _parse(raw, since, 0)] == [0, 1, 2]
    assert _parse(b"", since, 0) == []


def test_prepare_sorts_and_merges_rows_of_the_same_start() -> None:
    rows = [{"start": day(2), "x": 1.0}, {"start": day(1), "x": 0.0}, {"start": day(2), "x": 5.0, "y": 2.0}]
    assert _prepare(rows) == [{"start": day(1), "x": 0.0}, {"start": day(2), "x": 5.0, "y": 2.0}]


def test_measurement_and_total_statistics() -> None:
    rows = [
        {"start": day(1), "mean": 5.0, "low": 1.0, "high": 9.0, "rain": 2.0},
        {"start": day(2), "mean": 6.0, "rain": 0.5},
        {"start": day(3), "low": 0.0},
    ]
    assert _measurement_stats(rows, "mean", "low", "high") == [
        {"start": day(1), "mean": 5.0, "min": 1.0, "max": 9.0},
        {"start": day(2), "mean": 6.0, "min": 6.0, "max": 6.0},
    ]
    assert _measurement_stats(rows, "mean", None, None)[0] == {"start": day(1), "mean": 5.0, "min": 5.0, "max": 5.0}
    assert _total_stats(rows, "rain", 10.0) == [
        {"start": day(1), "state": 2.0, "sum": 12.0},
        {"start": day(2), "state": 0.5, "sum": 12.5},
    ]
    assert _total_stats(rows, "snow", 0.0) == []


# --- the import --------------------------------------------------------------


@pytest.fixture
def recorder():
    """The three doors to the recorder; `last` maps a statistic id to what
    the recorder already holds for it."""
    last: dict[str, Any] = {}

    async def last_statistics(_job, _hass, _number, statistic_id, _convert, _types):
        return last.get(statistic_id, {})

    instance = SimpleNamespace(async_add_executor_job=AsyncMock(side_effect=last_statistics))
    with (
        patch(f"{HISTORY}.get_instance", return_value=instance),
        patch(f"{HISTORY}.async_import_statistics", MagicMock()) as measurements,
        patch(f"{HISTORY}.async_add_external_statistics", MagicMock()) as totals,
    ):
        yield SimpleNamespace(last=last, measurements=measurements, totals=totals)


def sensor(hass: HomeAssistant, key: str, **kwargs: Any) -> str:
    """Register a station sensor the way the integration does."""
    return er.async_get(hass).async_get_or_create("sensor", DOMAIN, f"{ENTRY_ID}_{key}", **kwargs).entity_id


def written(door: MagicMock) -> dict[str, tuple[dict[str, Any], list[dict[str, Any]]]]:
    return {call.args[1]["statistic_id"]: (call.args[1], call.args[2]) for call in door.call_args_list}


async def test_daily_import(hass: HomeAssistant, swiss_now, recorder) -> None:
    temperature = sensor(hass, "temperature")
    humidity = sensor(hass, "humidity")
    gust = sensor(hass, "wind_gust")
    sensor(hass, "pressure_qnh")  # enabled, but the files carry no pressure
    sensor(hass, "dew_point")  # has no daily series
    sensor(hass, "wind_speed", disabled_by=er.RegistryEntryDisabler.USER)
    units = {
        "temperature": "°C",
        "humidity": "%",
        "wind_gust": "km/h",
        "pressure_qnh": "hPa",
        "dew_point": "°C",
        "wind_speed": "km/h",
        "snow_depth": "cm",  # no such entity
        "global_radiation": "W/m²",  # its group is not asked for
    }
    recorder.last[SUNSHINE] = {SUNSHINE: [{"start": day(1).timestamp(), "sum": 1000.0}]}
    recorder.last[DEGREE_DAYS] = {DEGREE_DAYS: [{"start": day(6), "sum": 50.0}]}
    recorder.last[PRECIPITATION] = {PRECIPITATION: [{"start": day(1), "sum": None}]}
    account = MagicMock()
    session = FakeSession({DAILY_RECENT: RECENT_DAYS, DAILY_HISTORICAL: OLDER_DAYS})

    with patch(SESSION, return_value=session):
        summary = await async_import_history(
            hass,
            station="BER",
            entry_id=ENTRY_ID,
            statistic_prefix="station_ber",
            units=units,
            years=2,
            resolution="daily",
            groups=set(GROUPS) - {"radiation"},
            account=account,
        )

    assert session.urls() == [DAILY_RECENT, DAILY_HISTORICAL]
    account.assert_called_once_with(2, len(RECENT_DAYS) + len(OLDER_DAYS))
    # the day both files carry counts once, the day before the span not at all
    assert summary == {
        "station": "BER",
        "resolution": "daily",
        "rows": 3,
        "first": "2026-11-05T00:00:00+00:00",
        "last": "2026-11-07T00:00:00+00:00",
        "statistics": {temperature: 3, humidity: 2, gust: 3, PRECIPITATION: 3, SUNSHINE: 2, DEGREE_DAYS: 3},
        "skipped": ["wind_speed", "snow_depth"],
    }

    measurements = written(recorder.measurements)
    assert set(measurements) == {temperature, humidity, gust}
    meta, stats = measurements[temperature]
    assert meta == {
        "statistic_id": temperature,
        "source": "recorder",
        "name": "temperature",
        "unit_of_measurement": "°C",
        "unit_class": "temperature",
        "has_sum": False,
        "mean_type": StatisticMeanType.ARITHMETIC,
    }
    assert stats == [
        {"start": day(5), "mean": 4.0, "min": 0.0, "max": 8.0},
        {"start": day(6), "mean": 5.0, "min": 1.0, "max": 9.0},
        {"start": day(7), "mean": 6.0, "min": 2.0, "max": 10.0},
    ]
    assert measurements[gust][1][2] == {"start": day(7), "mean": 55.0, "min": 55.0, "max": 55.0}

    totals = written(recorder.totals)
    assert set(totals) == {PRECIPITATION, SUNSHINE, DEGREE_DAYS}
    meta, stats = totals[PRECIPITATION]
    assert (meta["source"], meta["name"], meta["unit_of_measurement"]) == (DOMAIN, "BER Precipitation", "mm")
    assert meta["has_sum"] is True and meta["mean_type"] is StatisticMeanType.NONE
    assert [item["sum"] for item in stats] == [1.0, 3.5, 3.5]
    # the sum continues an earlier import that ended before these rows ...
    assert totals[SUNSHINE][1] == [
        {"start": day(5), "state": 60.0, "sum": 1060.0},
        {"start": day(6), "state": 120.0, "sum": 1180.0},
    ]
    # ... and starts again when the rows overlap what is already there
    assert [item["sum"] for item in totals[DEGREE_DAYS][1]] == [15.0, 29.0, 42.0]


async def test_hourly_import(hass: HomeAssistant, swiss_now, recorder) -> None:
    temperature = sensor(hass, "temperature")
    session = FakeSession({HOURLY_RECENT: HOURS})
    with patch(SESSION, return_value=session):
        summary = await async_import_history(
            hass,
            station="BER",
            entry_id=ENTRY_ID,
            statistic_prefix="station_ber",
            units={"temperature": "°C"},
            years=1,
            resolution="hourly",
            groups=set(GROUPS),
        )
    # the decade file is asked for too; the station has none
    assert session.urls() == [HOURLY_DECADE, HOURLY_RECENT]
    assert summary == {
        "station": "BER",
        "resolution": "hourly",
        "rows": 2,
        "first": "2026-11-08T08:00:00+00:00",
        "last": "2026-11-08T09:00:00+00:00",
        "statistics": {temperature: 2, PRECIPITATION: 2},
    }
    assert written(recorder.measurements)[temperature][1] == [
        {"start": day(8, 8), "mean": 5.0, "min": 4.5, "max": 5.5},
        {"start": day(8, 9), "mean": 6.0, "min": 5.5, "max": 6.0},
    ]
    # heating degree days exist per day only
    assert set(written(recorder.totals)) == {PRECIPITATION}


async def test_only_the_groups_asked_for(hass: HomeAssistant, swiss_now, recorder) -> None:
    sensor(hass, "temperature")
    with patch(SESSION, return_value=FakeSession({DAILY_RECENT: RECENT_DAYS})):
        summary = await async_import_history(
            hass,
            station="BER",
            entry_id=ENTRY_ID,
            statistic_prefix="station_ber",
            units={"temperature": "°C"},
            years=1,
            resolution="daily",
            groups={"sunshine"},
        )
    assert summary["statistics"] == {SUNSHINE: 1}
    assert "skipped" not in summary
    recorder.measurements.assert_not_called()


async def test_station_without_an_archive(hass: HomeAssistant, swiss_now, recorder) -> None:
    with patch(SESSION, return_value=FakeSession()), pytest.raises(HistoryError, match="No archive rows for station BER"):
        await async_import_history(
            hass, station="BER", entry_id=ENTRY_ID, statistic_prefix="station_ber", units={}, years=1, resolution="daily", groups=set(GROUPS)
        )
    recorder.totals.assert_not_called()


async def test_archive_that_does_not_answer(hass: HomeAssistant, swiss_now, recorder) -> None:
    session = FakeSession({DAILY_RECENT: FakeResponse(500)})
    with patch(SESSION, return_value=session), pytest.raises(HistoryError, match="HTTP 500"):
        await async_import_history(
            hass, station="BER", entry_id=ENTRY_ID, statistic_prefix="station_ber", units={}, years=1, resolution="daily", groups=set(GROUPS)
        )
