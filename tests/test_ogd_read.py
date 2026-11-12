"""The MeteoSwiss open-data reader against files served from memory:
the lists of points and stations, the run discovery, and the three ways
one point's rows are read out of a forecast file with byte ranges."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from functools import cache

import aiohttp
import pytest

from custom_components.swiss_meteo import ogd
from custom_components.swiss_meteo.const import (
    COLLECTION_FORECAST,
    FORECAST_META_POINTS_URL,
    PRECIP_STATIONS_META_URL,
    STAC_BASE,
    STATIONS_META_URL,
)
from custom_components.swiss_meteo.ogd import (
    OgdError,
    OgdUnavailable,
    ReadStats,
    _RangeFile,
    async_catalogue_latest_run,
    async_fetch_forecast,
    async_fetch_points,
    async_fetch_precip_reading,
    async_fetch_precip_stations,
    async_fetch_station_reading,
    async_fetch_stations,
    async_find_latest_run,
    async_read_point,
    forecast_file_url,
    precip_now_url,
    station_now_url,
)

from .fakes import FakeResponse, FakeSession

RUN = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
HEADER = b"point_id;point_type_id;Date;value\n"

# An invented country: 300 stations, 1500 postal codes, 300 mountain spots.
STATIONS = [(number, 1) for number in range(1, 301)]
POSTAL = [(100100 + number * 500, 2) for number in range(1500)]
MOUNTAINS = [(number, 3) for number in range(1, 301)]
POINTS = STATIONS + POSTAL + MOUNTAINS
ZURICH = (800100, 2)
NOWHERE = (800101, 2)

EVERYWHERE = [(1, 1), (300, 1), (100100, 2), ZURICH, (849600, 2), (1, 3), (300, 3)]


def stamps(count: int, step: timedelta = HOUR) -> list[datetime]:
    return [RUN + step * index for index in range(count)]


def value(point: tuple[int, int], index: int) -> float:
    return float(point[0] % 97) + index * 0.5


def row(point: tuple[int, int], when: datetime, index: int) -> bytes:
    return f"{point[0]};{point[1]};{when:%Y%m%d%H%M};{value(point, index)}\n".encode()


def expected(point: tuple[int, int], times: list[datetime]) -> list[tuple[datetime, float]]:
    return [(when, value(point, index)) for index, when in enumerate(times)]


def point_major(times: list[datetime], points: list[tuple[int, int]] | None = None) -> bytes:
    """All rows of a point together, the points grouped by type."""
    return HEADER + b"".join(row(point, when, index) for point in points or POINTS for index, when in enumerate(times))


def date_major(
    times: list[datetime],
    padding: dict[int, int] | None = None,
    until: dict[tuple[int, int], int] | None = None,
) -> bytes:
    """All points of a timestamp together. `padding` puts that many rows of
    an unrelated type at the start of a block (the block gets longer than
    its neighbours); `until` drops a point from that block on."""
    parts = [HEADER]
    for index, when in enumerate(times):
        for number in range((padding or {}).get(index, 0)):
            parts.append(f"{number};9;{when:%Y%m%d%H%M};0.0\n".encode())
        for point in POINTS:
            if until and index >= until.get(point, len(times)):
                continue
            parts.append(row(point, when, index))
    return b"".join(parts)


@cache
def hourly_by_point() -> bytes:
    return point_major(stamps(12))


@cache
def daily_by_date() -> bytes:
    return date_major(stamps(8, DAY))


@cache
def hourly_by_date() -> bytes:
    return date_major(stamps(64))


async def read(body: bytes, point: tuple[int, int], param: str, **session_options):
    url = forecast_file_url(RUN, param)
    session = FakeSession({url: body}, **session_options)
    stats = ReadStats()
    rows = await async_read_point(session, url, point, param, stats)
    return rows, stats


def range_file(body: bytes, session: FakeSession | None = None) -> _RangeFile:
    url = "https://example.invalid/file.csv"
    return _RangeFile(session or FakeSession({url: body}), url, len(body), ReadStats())


# --- plain fetches ---------------------------------------------------------------


async def test_fetch_turns_every_failure_into_unavailable() -> None:
    url = "https://example.invalid/list.csv"
    assert await ogd._fetch(FakeSession({url: b"abc"}), url) == b"abc"
    with pytest.raises(OgdUnavailable, match="HTTP 404 for list.csv"):
        await ogd._fetch(FakeSession(), url)
    with pytest.raises(OgdUnavailable, match="ClientError for list.csv"):
        await ogd._fetch(FakeSession({url: aiohttp.ClientError("boom")}), url)
    with pytest.raises(OgdUnavailable, match="TimeoutError for list.csv"):
        await ogd._fetch(FakeSession({url: asyncio.TimeoutError()}), url)


async def test_points_are_read_and_broken_rows_skipped() -> None:
    body = (
        "point_id;point_type_id;station_abbr;postal_code;point_name;"
        "point_coordinates_wgs84_lat;point_coordinates_wgs84_lon;point_height_masl\n"
        "800100;2;;8001;Zürich;47.3769;8.5417;408.0\n"
        "48;1;BER;;Bern / Zollikofen;46.9907;7.4640;\n"
        "x;2;;9999;Broken;47.0;8.0;500\n"
    ).encode("latin-1")
    points = await async_fetch_points(FakeSession({FORECAST_META_POINTS_URL: body}))
    assert [point.key for point in points] == [(800100, 2), (48, 1)]
    assert points[0].name == "Zürich"
    assert points[0].postal_code == "8001"
    assert points[0].height == 408.0
    assert points[1].station_abbr == "BER"
    assert points[1].height is None

    header_only = body.split(b"\n", 1)[0] + b"\n"
    with pytest.raises(OgdError, match="point list is empty"):
        await async_fetch_points(FakeSession({FORECAST_META_POINTS_URL: header_only}))


async def test_stations_are_read_and_broken_rows_skipped() -> None:
    body = (
        "station_abbr;station_name;station_canton;station_height_masl;"
        "station_coordinates_wgs84_lat;station_coordinates_wgs84_lon\n"
        "BER;Bern / Zollikofen;BE;553;46.9907;7.4640\n"
        "GVE;Genève / Cointrin;GE;411;46.2475;6.1278\n"
        "BAD;Broken;XX;1;north;east\n"
    ).encode("latin-1")
    stations = await async_fetch_stations(FakeSession({STATIONS_META_URL: body}))
    assert [station.abbr for station in stations] == ["BER", "GVE"]
    assert stations[1].name == "Genève / Cointrin"
    assert stations[0].canton == "BE"
    assert stations[0].height == 553.0

    header_only = body.split(b"\n", 1)[0] + b"\n"
    with pytest.raises(OgdError, match="station list is empty"):
        await async_fetch_stations(FakeSession({STATIONS_META_URL: header_only}))


async def test_station_reading_is_the_last_row() -> None:
    url = station_now_url("BER")
    body = (
        b"station_abbr;reference_timestamp;tre200s0;ure200s0;rre150z0\n"
        b"BER;08.11.2026 10:10;7.9;81.0;0.0\n"
        b"BER;08.11.2026 10:20;8.1;80.2;\n"
    )
    reading = await async_fetch_station_reading(FakeSession({url: body}), "BER")
    assert reading.abbr == "BER"
    assert reading.timestamp == datetime(2026, 11, 8, 10, 20, tzinfo=UTC)
    assert reading.values == {"tre200s0": 8.1, "ure200s0": 80.2, "rre150z0": None}

    with pytest.raises(OgdError, match="has no rows"):
        await async_fetch_station_reading(FakeSession({url: body.split(b"\n", 1)[0] + b"\n"}), "BER")
    broken = b"station_abbr;reference_timestamp;tre200s0\nBER;yesterday;7.9\n"
    with pytest.raises(OgdError, match="bad timestamp"):
        await async_fetch_station_reading(FakeSession({url: broken}), "BER")


async def test_precipitation_stations_have_a_list_of_their_own() -> None:
    body = (
        "station_abbr;station_name;station_canton;station_height_masl;"
        "station_coordinates_wgs84_lat;station_coordinates_wgs84_lon\n"
        "WAG;Waldegg;ZH;545;47.362269;8.454789\n"
        "BEP;Belp;BE;510;46.906094;7.505339\n"
    ).encode("latin-1")
    session = FakeSession({PRECIP_STATIONS_META_URL: body})
    stations = await async_fetch_precip_stations(session)
    assert PRECIP_STATIONS_META_URL != STATIONS_META_URL
    assert session.urls() == [PRECIP_STATIONS_META_URL]
    assert [(station.abbr, station.name, station.height) for station in stations] == [("WAG", "Waldegg", 545.0), ("BEP", "Belp", 510.0)]

    with pytest.raises(OgdUnavailable, match="HTTP 404"):
        await async_fetch_precip_stations(FakeSession())


async def test_precipitation_reading_is_the_last_row() -> None:
    url = precip_now_url("WAG")
    assert url.endswith("/ch.meteoschweiz.ogd-smn-precip/wag/ogd-smn-precip_wag_t_now.csv")
    assert url != station_now_url("WAG")
    body = (
        b"station_abbr;reference_timestamp;rre150z0\n"
        b"WAG;08.11.2026 10:10;0\n"
        b"WAG;08.11.2026 10:20;1.4\n"
    )
    reading = await async_fetch_precip_reading(FakeSession({url: body}), "WAG")
    assert reading.abbr == "WAG"
    assert reading.timestamp == datetime(2026, 11, 8, 10, 20, tzinfo=UTC)
    assert reading.values == {"rre150z0": 1.4}

    with pytest.raises(OgdError, match="station file of WAG has no rows"):
        await async_fetch_precip_reading(FakeSession({url: body.split(b"\n", 1)[0] + b"\n"}), "WAG")


# --- size and run discovery ------------------------------------------------------


async def test_size_from_head_or_from_a_one_byte_range() -> None:
    url = "https://example.invalid/file.csv"
    body = b"x" * 4321
    assert await ogd._head_size(FakeSession({url: body}), url) == 4321
    assert await ogd._head_size(FakeSession(), url) is None
    assert await ogd._head_size(FakeSession({url: FakeResponse(403)}), url) is None

    # HEAD without a length: the total comes from the range answer ...
    session = FakeSession({url: body}, head_length=False)
    assert await ogd._head_size(session, url) == 4321
    assert session.calls[-1][2]["Range"] == "bytes=0-0"
    # ... or from a full answer of a host that ignores ranges
    assert await ogd._head_size(FakeSession({url: body}, head_length=False, honour_range=False), url) == 4321

    def gone_after_head(method: str, _url: str, _headers: dict[str, str]) -> FakeResponse:
        return FakeResponse(200) if method == "HEAD" else FakeResponse(404)

    assert await ogd._head_size(FakeSession({url: gone_after_head}), url) is None


async def test_size_failures() -> None:
    url = "https://example.invalid/file.csv"
    with pytest.raises(OgdUnavailable, match="HTTP 500 for file.csv"):
        await ogd._head_size(FakeSession({url: FakeResponse(500)}), url)
    with pytest.raises(OgdUnavailable, match="no size for file.csv"):
        await ogd._head_size(FakeSession({url: FakeResponse(200)}), url)
    with pytest.raises(OgdUnavailable, match="ClientError for file.csv"):
        await ogd._head_size(FakeSession({url: aiohttp.ClientError("boom")}), url)


async def test_latest_run_is_probed_backwards() -> None:
    now = RUN + timedelta(hours=2, minutes=30)
    session = FakeSession({forecast_file_url(RUN, "jp2000d0"): b"x" * 100})
    assert await async_find_latest_run(session, now) == RUN
    assert session.urls("HEAD") == [forecast_file_url(RUN + HOUR * back, "jp2000d0") for back in (2, 1, 0)]

    nothing = FakeSession()
    assert await async_find_latest_run(nothing, now) is None
    assert len(nothing.calls) == 7
    assert await async_find_latest_run(session, now, max_back=1) is None


async def test_latest_run_from_the_catalogue() -> None:
    url = f"{STAC_BASE}/{COLLECTION_FORECAST}/items?limit=3"
    catalogue = {
        "features": [
            {"assets": {"vnut12.lssw.202611080900.tre200h0.csv": {}, "vnut12.lssw.202611081000.tre200h0.csv": {}, "readme.txt": {}}},
            {"assets": {"vnut12.lssw.202611080800.tre200h0.csv": {}}},
            {},
        ]
    }
    assert await async_catalogue_latest_run(FakeSession({url: json.dumps(catalogue).encode()})) == RUN + HOUR
    assert await async_catalogue_latest_run(FakeSession({url: b'{"features": []}'})) is None
    with pytest.raises(OgdError, match="STAC answer"):
        await async_catalogue_latest_run(FakeSession({url: b"<html>"}))
    with pytest.raises(OgdError, match="STAC answer"):
        await async_catalogue_latest_run(FakeSession({url: b'{"other": 1}'}))


# --- byte ranges -------------------------------------------------------------------


async def test_range_read_counts_and_clips() -> None:
    body = bytes(range(256)) * 4
    rf = range_file(body)
    assert await rf.read(10, 5) == body[10:15]
    assert await rf.read(-20, 5) == body[0:5]
    assert await rf.read(1020, 100) == body[1020:]
    assert await rf.read(5000, 10) == b""
    assert rf.stats.requests == 3
    assert rf.stats.bytes == 5 + 5 + 4

    # A host that ignores the range sends everything: the slice is taken.
    url = "https://example.invalid/file.csv"
    whole = range_file(body, FakeSession({url: body}, honour_range=False))
    assert await whole.read(10, 5) == body[10:15]
    assert whole.stats.bytes == len(body)


async def test_range_read_failures() -> None:
    url = "https://example.invalid/file.csv"
    with pytest.raises(OgdUnavailable, match="HTTP 503 for file.csv"):
        await range_file(b"abc", FakeSession({url: FakeResponse(503)})).read(0, 3)
    with pytest.raises(OgdUnavailable, match="ClientError for file.csv"):
        await range_file(b"abc", FakeSession({url: aiohttp.ClientError("boom")})).read(0, 3)


async def test_first_row_at_an_offset() -> None:
    body = HEADER + row(ZURICH, RUN, 0) + row(ZURICH, RUN + HOUR, 1)
    rf = range_file(body)
    # from the start the header is skipped, from inside a row the next one is taken
    assert await ogd._row_at(rf, 0) == ((800100, 2, "202611080900"), len(HEADER))
    second = len(HEADER) + len(row(ZURICH, RUN, 0))
    assert await ogd._row_at(rf, len(HEADER) + 3) == ((800100, 2, "202611081000"), second)

    # no line end in sight, even in the larger read
    assert await ogd._row_at(range_file(b"x" * 20000), 10) == (None, 10)
    # nothing but lines that are no data rows
    key, _offset = await ogd._row_at(range_file(b"a\n" + b"junk\n" * 6), 1)
    assert key is None
    # the row after the offset is cut off
    key, _offset = await ogd._row_at(range_file(b"a\n800100;2;2026"), 1)
    assert key is None


def test_rows_of_a_chunk_without_a_line_end() -> None:
    assert ogd._rows_of(b"800100;2;202611080900;1.0", 0, ZURICH, False) == []


# --- reading one point ---------------------------------------------------------------


async def test_small_file_is_read_whole() -> None:
    times = stamps(5)
    body = point_major(times, [(1, 1), ZURICH, (5, 3)])
    rows, stats = await read(body, ZURICH, "rre150h0")
    assert rows == expected(ZURICH, times)
    assert stats.requests == 2  # the size and the file
    assert stats.bytes == len(body)

    with pytest.raises(OgdError, match="point 2/800101 not in"):
        await read(body, NOWHERE, "rre150h0")


async def test_missing_file() -> None:
    url = forecast_file_url(RUN, "rre150h0")
    with pytest.raises(OgdUnavailable, match="missing file"):
        await async_read_point(FakeSession(), url, ZURICH, "rre150h0", ReadStats())


@pytest.mark.parametrize("point", EVERYWHERE)
async def test_rows_grouped_by_point(point: tuple[int, int]) -> None:
    body = hourly_by_point()
    assert len(body) > ogd._SMALL_FILE
    rows, stats = await read(body, point, "rre150h0")
    assert rows == expected(point, stamps(12))
    assert stats.bytes < len(body) / 5


async def test_rows_grouped_by_point_without_the_point() -> None:
    with pytest.raises(OgdError):
        await read(hourly_by_point(), NOWHERE, "rre150h0")


@pytest.mark.parametrize("point", [(104, 2), (130, 2), (158, 2)])
async def test_block_longer_than_the_first_window(point: tuple[int, int]) -> None:
    """A point with more rows than one read holds: the window is widened."""
    times = stamps(800, timedelta(minutes=1))
    body = point_major(times, [(100 + number, 2) for number in range(60)])
    rows, stats = await read(body, point, "rre150h0")
    assert rows == expected(point, times)
    assert stats.bytes < len(body) / 5


@pytest.mark.parametrize("point", EVERYWHERE)
async def test_daily_rows_grouped_by_date(point: tuple[int, int]) -> None:
    body = daily_by_date()
    assert ogd._SMALL_FILE < len(body) <= 3 * 1024 * 1024
    rows, stats = await read(body, point, "tre200px")
    assert rows == expected(point, stamps(8, DAY))
    assert stats.bytes < len(body) / 2


async def test_daily_rows_with_a_block_out_of_step() -> None:
    """One block is much longer than the others: the prediction misses and
    every block is searched instead."""
    times = stamps(8, DAY)
    rows, _stats = await read(date_major(times, padding={4: 700}), ZURICH, "tre200px")
    assert rows == expected(ZURICH, times)


async def test_daily_rows_without_the_point() -> None:
    with pytest.raises(OgdError, match="point 2/800101 not in"):
        await read(daily_by_date(), NOWHERE, "tre200px")


async def test_date_major_helpers() -> None:
    times = stamps(8, DAY)
    assert await ogd._read_block_search(range_file(daily_by_date()), ZURICH) == [
        row(ZURICH, when, index).rstrip() for index, when in enumerate(times)
    ]
    # a single timestamp block: nothing to predict, the file is read whole
    single = date_major(stamps(1))
    assert await ogd._read_date_major_small(range_file(single), ZURICH) == [row(ZURICH, RUN, 0).rstrip()]
    # no row of the wanted timestamp follows: the upper bound is the answer
    assert await ogd._date_boundary(range_file(single), 0, len(single), "999999999999") == len(single)


@pytest.mark.parametrize("point", EVERYWHERE)
async def test_hourly_rows_grouped_by_date(point: tuple[int, int]) -> None:
    body = hourly_by_date()
    assert len(body) > 3 * 1024 * 1024
    rows, stats = await read(body, point, "tre200h0")
    assert rows == expected(point, stamps(64))
    assert stats.bytes < len(body) / 2


@pytest.mark.parametrize("padding", [{13: 300}, {20: 300}, {11: 300, 30: 300}])
async def test_hourly_rows_with_blocks_out_of_step(padding: dict[int, int]) -> None:
    """Longer blocks move every later row: the reader finds its way back."""
    times = stamps(64)
    rows, _stats = await read(date_major(times, padding=padding), ZURICH, "tre200h0")
    assert rows == expected(ZURICH, times)


async def test_hourly_rows_that_end_early() -> None:
    """The point is dropped from the file after some blocks: the reader
    gives up after a few misses and returns what it found."""
    times = stamps(64)
    rows, stats = await read(date_major(times, until={ZURICH: 14}), ZURICH, "tre200h0")
    assert rows == expected(ZURICH, times)[:14]
    assert stats.bytes < 1024 * 1024


async def test_hourly_rows_without_the_point() -> None:
    with pytest.raises(OgdError, match="first blocks of a date-major file"):
        await read(hourly_by_date(), NOWHERE, "tre200h0")


# --- a whole run -----------------------------------------------------------------------


async def test_forecast_lists_what_could_not_be_read() -> None:
    times = stamps(5)
    body = point_major(times, [ZURICH])
    session = FakeSession(
        {
            forecast_file_url(RUN, "rre150h0"): body,
            forecast_file_url(RUN, "fu3010h0"): body,
            forecast_file_url(RUN, "sre000h0"): point_major(times, [(1, 1)]),
        }
    )
    data = await async_fetch_forecast(session, RUN, ZURICH, ("rre150h0", "fu3010h0", "sre000h0", "gre000h0"))
    assert data.run == RUN
    assert data.point == ZURICH
    assert set(data.series) == {"rre150h0", "fu3010h0"}
    assert data.series["rre150h0"] == expected(ZURICH, times)
    assert sorted(data.missing) == ["gre000h0", "sre000h0"]
    assert data.stats.requests == 7  # four sizes, three files
    assert data.stats.bytes > 0

    with pytest.raises(OgdUnavailable, match="no forecast file of run 2026-11-08 09:00"):
        await async_fetch_forecast(FakeSession(), RUN, ZURICH, ("rre150h0", "fu3010h0"))
