"""The precipitation radar: geometry, reading the field out of a frame
file, what two frames say about the rain around a point, the pictures of
the loop, and the coordinator against frames served from memory."""
from __future__ import annotations

import asyncio
import base64
import logging
import math
import struct
import sys
import zlib
from array import array
from datetime import UTC, datetime, timedelta, timezone
from functools import cache
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant

from custom_components.swiss_meteo.radar import (
    COLS,
    CROP,
    CROP_RADIUS,
    LEVELS,
    PALETTE,
    RADAR_BASE,
    ROWS,
    X0,
    Y0,
    Frame,
    RadarCoordinator,
    RadarData,
    RadarError,
    _level,
    _motion,
    analyse,
    crop_field,
    decode_crop,
    decode_field,
    frame_url,
    lv95,
    pixel_of,
    render_frames,
    render_png,
    slot,
)

from .conftest import NOW, make_entry
from .fakes import FakeResponse, FakeSession

SESSION = "custom_components.swiss_meteo.radar.async_get_clientsession"
ASYNCIO = "custom_components.swiss_meteo.radar.asyncio"

M = CROP_RADIUS
MINUTES = timedelta(minutes=1)
# the newest frame published at the fixed moment (10:30 UTC)
T = datetime(2026, 11, 8, 10, 25, tzinfo=UTC)
ROW, COL = pixel_of(47.3769, 8.5417)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@cache
def radar_file() -> bytes:
    """A frame file as the reader sees it: bytes it has to skip, then the
    compressed field with rain at the point and in a corner of its crop."""
    field = array("d", bytes(8 * COLS * ROWS))
    for row, col, rate in (
        (ROW, COL, 1.5),
        (ROW - M, COL - M, 2.0),
        (ROW, COL + 1, math.nan),
        (ROW + 1, COL, -1.0),
        (0, 0, 3.0),
        (ROWS - 1, COLS - 1, 4.0),
    ):
        field[row * COLS + col] = rate
    if sys.byteorder == "little":
        field.byteswap()
    return (
        b"\x89HDF\r\n"
        + b"\x78\x00"  # an x that starts no stream
        + b"\x78\x9c\xff\xff"  # a header followed by rubbish
        + zlib.compress(b"too short")  # a stream of the wrong length
        + zlib.compress(field.tobytes())
    )


def crop_of(cells: dict[tuple[int, int], float]) -> array:
    """A crop with rain at the given offsets (rows, columns) from the point."""
    crop = array("f", bytes(4 * CROP * CROP))
    for (dr, dc), rate in cells.items():
        crop[(M + dr) * CROP + (M + dc)] = rate
    return crop


def block(dr: int, dc: int, size: int = 5, rate: float = 2.0) -> dict[tuple[int, int], float]:
    """A square rain cell whose top left corner is at the given offset."""
    return {(dr + i, dc + j): rate for i in range(size) for j in range(size)}


def png_rows(png: bytes) -> list[bytes]:
    """The palette indexes of a picture, row by row."""
    assert png[:8] == PNG_SIGNATURE
    position, chunks = 8, {}
    while position < len(png):
        (length,) = struct.unpack(">I", png[position : position + 4])
        kind = png[position + 4 : position + 8]
        data = png[position + 8 : position + 8 + length]
        (checksum,) = struct.unpack(">I", png[position + 8 + length : position + 12 + length])
        assert checksum == zlib.crc32(kind + data)
        chunks[kind] = data
        position += 12 + length
    width, height, depth, colour = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (width, height, depth, colour) == (CROP, CROP, 8, 3)
    assert len(chunks[b"PLTE"]) == 3 * len(PALETTE)
    assert chunks[b"tRNS"][0] == 0  # no rain is transparent
    raw = zlib.decompress(chunks[b"IDAT"])
    return [raw[y * (width + 1) + 1 : (y + 1) * (width + 1)] for y in range(height)]


# --- geometry and file names -------------------------------------------------


def test_swiss_coordinates_and_pixel_of_a_point() -> None:
    # the reference point of the projection (the old observatory in Bern)
    east, north = lv95(169028.66 / 3600, 26782.5 / 3600)
    assert east == pytest.approx(2600072.37)
    assert north == pytest.approx(1200147.07)
    assert pixel_of(169028.66 / 3600, 26782.5 / 3600) == (279, 345)
    assert 0 <= ROW < ROWS and 0 <= COL < COLS


def test_frame_url_names_the_slot_in_utc() -> None:
    expected = f"{RADAR_BASE}/20261108-ch/rzc263121025vl.001.h5"
    assert frame_url(T) == expected
    assert frame_url(T.astimezone(timezone(timedelta(hours=1)))) == expected


def test_slot_is_the_newest_published_five_minutes() -> None:
    assert slot(NOW) == T
    assert slot(datetime(2026, 11, 8, 10, 31, 10, tzinfo=UTC)) == T + 5 * MINUTES
    assert slot(datetime(2026, 11, 8, 10, 0, 30, tzinfo=UTC)) == datetime(2026, 11, 8, 9, 55, tzinfo=UTC)


# --- reading a frame ---------------------------------------------------------


def test_decode_field_finds_the_stream_between_other_bytes() -> None:
    field = decode_field(radar_file())
    assert len(field) == COLS * ROWS
    assert field[ROW * COLS + COL] == 1.5
    assert math.isnan(field[ROW * COLS + COL + 1])
    assert field[0] == 3.0


@pytest.mark.parametrize("raw", [b"", b"nothing compressed here", b"ends with an x", zlib.compress(b"short")])
def test_decode_field_without_a_field(raw: bytes) -> None:
    with pytest.raises(RadarError, match="no zlib stream"):
        decode_field(raw)


def test_crop_around_the_point_drops_what_is_no_rain() -> None:
    crop = decode_crop(radar_file(), ROW, COL)
    assert len(crop) == CROP * CROP
    assert crop[M * CROP + M] == 1.5
    assert crop[0] == 2.0
    assert crop[M * CROP + M + 1] == 0.0  # no data
    assert crop[(M + 1) * CROP + M] == 0.0  # below zero
    assert sum(1 for value in crop if value) == 2


def test_crop_at_the_edge_of_the_composite() -> None:
    field = decode_field(radar_file())
    top_left = crop_field(field, 0, 0)
    assert top_left[M * CROP + M] == 3.0
    assert sum(1 for value in top_left if value) == 1
    bottom_right = crop_field(field, ROWS - 1, COLS - 1)
    assert bottom_right[M * CROP + M] == 4.0
    assert sum(1 for value in bottom_right if value) == 1


# --- analysis ----------------------------------------------------------------


def test_dry_frame() -> None:
    data = analyse([Frame(T, crop_of({}))], NOW)
    assert data.frame_ts == T and data.fetched == NOW and data.frames == 1
    assert data.rate == 0.0 and data.rate_point == 0.0
    assert data.raining is False and data.approaching is False
    assert data.nearest_km is None and data.nearest_bearing is None
    assert data.speed_kmh is None and data.direction is None and data.motion is None
    assert data.eta_min is None
    assert data.rain_pixels_window == 0


def test_rain_next_to_the_point_counts_as_raining() -> None:
    data = analyse([Frame(T, crop_of({(1, 1): 0.2}))], NOW)
    assert data.rate == 0.2
    assert data.rate_point == 0.0
    assert data.raining is True and data.approaching is True
    assert data.eta_min == 0
    # too weak to be tracked as a cell
    assert data.rain_pixels_window == 0 and data.nearest_km is None


def test_nearest_rain_with_distance_and_bearing() -> None:
    data = analyse([Frame(T, crop_of({(-30, 0): 1.0, (0, 40): 1.0, (70, 0): 5.0}))], NOW)
    assert data.rain_pixels_window == 3
    assert data.nearest_km == 30.0
    assert data.nearest_bearing == 0  # north
    east = analyse([Frame(T, crop_of({(0, 40): 1.0}))], NOW)
    assert (east.nearest_km, east.nearest_bearing) == (40.0, 90)
    # rain is only looked for within 60 km
    far = analyse([Frame(T, crop_of({(70, 0): 5.0}))], NOW)
    assert far.rain_pixels_window == 1 and far.nearest_km is None


def test_rain_moving_towards_the_point() -> None:
    frames = [Frame(T - 5 * MINUTES, crop_of(block(-2, -32))), Frame(T, crop_of(block(-2, -27)))]
    data = analyse(frames, NOW)
    assert data.motion == (0.0, 1.0)  # one pixel a minute to the east
    assert data.speed_kmh == 60.0
    assert data.direction == 90
    assert data.nearest_km == 23.0 and data.nearest_bearing == 270
    assert data.raining is False
    assert data.eta_min == 23
    assert data.approaching is True
    assert data.frames == 2


def test_rain_moving_away_or_passing_by_gives_no_arrival() -> None:
    away = analyse([Frame(T - 5 * MINUTES, crop_of(block(-2, -27))), Frame(T, crop_of(block(-2, -32)))], NOW)
    assert away.speed_kmh == 60.0 and away.direction == 270
    assert away.eta_min is None and away.approaching is False

    passing = analyse([Frame(T - 5 * MINUTES, crop_of(block(10, -32))), Frame(T, crop_of(block(10, -27)))], NOW)
    assert passing.direction == 90
    assert passing.eta_min is None

    # slow rain far away: later than the two hours looked ahead
    slow = analyse([Frame(T - 5 * MINUTES, crop_of(block(-2, -61))), Frame(T, crop_of(block(-2, -60)))], NOW)
    assert slow.speed_kmh == 12.0
    assert slow.eta_min is None


def test_standing_rain_has_no_direction() -> None:
    crop = crop_of(block(20, 20))
    data = analyse([Frame(T - 5 * MINUTES, crop), Frame(T, crop)], NOW)
    assert data.motion == (0.0, 0.0)
    assert data.speed_kmh == 0.0
    assert data.direction is None
    assert data.eta_min is None

    over_the_point = crop_of(block(-2, -2))
    raining = analyse([Frame(T - 5 * MINUTES, over_the_point), Frame(T, over_the_point)], NOW)
    assert raining.raining is True and raining.rate == 2.0 and raining.rate_point == 2.0
    assert raining.eta_min == 0
    assert raining.nearest_km == 0.0


def test_motion_needs_a_recent_frame_with_enough_rain() -> None:
    cur = crop_of(block(-2, -27))
    old = analyse([Frame(T - 15 * MINUTES, crop_of(block(-2, -32))), Frame(T, cur)], NOW)
    assert old.motion is None and old.speed_kmh is None and old.eta_min is None
    # the frame before was dry: nothing to compare
    dry_before = analyse([Frame(T - 5 * MINUTES, crop_of({})), Frame(T, cur)], NOW)
    assert dry_before.motion is None
    # the newest of the earlier frames is the one compared with
    three = analyse(
        [Frame(T - 10 * MINUTES, crop_of(block(-2, -40))), Frame(T - 5 * MINUTES, crop_of(block(-2, -32))), Frame(T, cur)],
        NOW,
    )
    assert three.motion == (0.0, 1.0)
    # no rain now: the motion is not looked for
    cleared = analyse([Frame(T - 5 * MINUTES, cur), Frame(T, crop_of({}))], NOW)
    assert cleared.motion is None


def test_motion_of_a_large_rain_field_is_estimated_from_a_sample() -> None:
    prev = crop_of(block(-30, -30, size=60))
    cur = crop_of(block(-28, -30, size=60))
    assert _motion(prev, cur) == (2, 0)


def test_approaching_within_half_an_hour() -> None:
    def data(raining: bool, eta: int | None) -> RadarData:
        return RadarData(T, 0.0, 0.0, raining, None, None, None, None, eta, 0, None, 1, NOW)

    assert data(True, 0).approaching is True
    assert data(False, 30).approaching is True
    assert data(False, 31).approaching is False
    assert data(False, None).approaching is False


# --- pictures ----------------------------------------------------------------


def test_rain_rate_classes() -> None:
    assert [_level(rate) for rate in (0.05, 0.1, 0.3, 1.0, 99.9, 100.0)] == [0, 1, 2, 3, 6, 7]
    assert len(PALETTE) == len(LEVELS) + 1


def test_picture_of_a_crop_and_of_a_shifted_crop() -> None:
    crop = crop_of({(0, 0): 0.05, (-M, -M): 0.1, (5, 7): 3.0, (10, 10): 150.0})
    rows = png_rows(render_png(crop))
    assert rows[M][M] == 0  # below the lowest class
    assert rows[0][0] == 1
    assert rows[M + 5][M + 7] == 4
    assert rows[M + 10][M + 10] == 7
    assert sum(1 for row in rows for index in row if index) == 3

    moved = png_rows(render_png(crop, (3, -2)))
    assert moved[M + 8][M + 5] == 4
    assert moved[M + 5][M + 7] == 0
    # the cell in the corner has left the picture, and nothing came in
    assert sum(1 for row in moved for index in row if index) == 2


def test_loop_frames_past_and_extrapolated() -> None:
    frames = [Frame(T - 5 * MINUTES, crop_of({(0, 0): 1.0})), Frame(T, crop_of({(0, 0): 1.0}))]
    assert render_frames([], (0.0, 1.0)) == []
    past = render_frames(frames, None)
    assert [(entry["ts"], entry["kind"], entry["offset_min"]) for entry in past] == [
        ((T - 5 * MINUTES).isoformat(), "past", 0),
        (T.isoformat(), "past", 0),
    ]
    assert png_rows(base64.b64decode(past[1]["png"]))[M][M] == 3
    # a field that hardly moves is not extrapolated
    assert len(render_frames(frames, (0.01, 0.0))) == 2

    loop = render_frames(frames, (0.0, 0.2), forecast_minutes=15)
    assert [(entry["kind"], entry["offset_min"]) for entry in loop[2:]] == [("forecast", 5), ("forecast", 10), ("forecast", 15)]
    assert loop[-1]["ts"] == (T + 15 * MINUTES).isoformat()
    ten = png_rows(base64.b64decode(loop[3]["png"]))
    assert ten[M][M + 2] == 3 and ten[M][M] == 0


# --- coordinator -------------------------------------------------------------


@pytest.fixture
def no_wait():
    """The pause between two history frames, without the waiting."""
    with patch(ASYNCIO, SimpleNamespace(sleep=AsyncMock())) as fake:
        yield fake.sleep


def served(*slots: datetime) -> FakeSession:
    return FakeSession({frame_url(ts): radar_file() for ts in slots})


async def test_point_outside_the_composite(hass: HomeAssistant, swiss_now) -> None:
    entry = make_entry(hass, {"point_lat": 60.0, "point_lon": 30.0})
    with pytest.raises(ValueError, match="outside the radar composite"):
        RadarCoordinator(hass, entry)


async def test_first_read_and_history(hass: HomeAssistant, swiss_now, no_wait) -> None:
    session = served(T, T - 5 * MINUTES, T - 20 * MINUTES)
    traffic: list[tuple[int, int]] = []
    coordinator = RadarCoordinator(hass, make_entry(hass), lambda requests, nbytes: traffic.append((requests, nbytes)))
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)

        data = coordinator.data
        assert coordinator.last_update_success and coordinator.fresh
        assert data.frame_ts == T
        assert data.rate == 1.5 and data.raining is True
        assert data.frames == 2  # the newest and the one before, for the motion
        # the rest of the two hours follows in the background
        assert [frame.ts for frame in coordinator.frames] == [T - 20 * MINUTES, T - 5 * MINUTES, T]
        assert session.urls("GET")[:3] == [frame_url(T), frame_url(T - 5 * MINUTES), frame_url(T - 10 * MINUTES)]
        assert len(session.calls) == 25
        assert no_wait.await_count == 23
        assert listener.call_count == 2  # after the read and after the history
        # every request is counted, with the bytes of the frames that exist
        assert len(traffic) == 25
        assert sum(nbytes for _requests, nbytes in traffic) == 3 * len(radar_file())
        assert session.calls[0][2]["User-Agent"].startswith("SwissMeteo/")

        # nothing new: held frames and slots known to be missing are not asked for again
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert len(session.calls) == 25

        card = await coordinator.async_frames_for_card()
    unsubscribe()
    assert coordinator.latest_png().startswith(PNG_SIGNATURE)
    assert coordinator.origin_km == ((X0 + (COL - M) * 1000) / 1000, (Y0 - (ROW - M) * 1000) / 1000)
    assert card["size"] == CROP and card["km_per_px"] == 1
    assert card["origin"] == {"e_km": coordinator.origin_km[0], "n_km": coordinator.origin_km[1]}
    assert card["center"] == {"row": M, "col": M}
    assert card["levels"] == list(LEVELS)
    assert card["palette"][1] == list(PALETTE[1])
    assert card["newest"] == T.isoformat()
    assert card["motion_kmh"] is None and card["direction"] is None
    assert "not an official nowcast" in card["estimate"]
    assert [frame["kind"] for frame in card["frames"]] == ["past", "past", "past"]


async def test_newest_slot_not_published_yet(hass: HomeAssistant, swiss_now, no_wait) -> None:
    session = served(T - 5 * MINUTES)
    coordinator = RadarCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert coordinator.data.frame_ts == T - 5 * MINUTES
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.last_update_success
    assert session.urls().count(frame_url(T)) == 1


async def test_no_frame_at_all(hass: HomeAssistant, swiss_now, no_wait, caplog) -> None:
    coordinator = RadarCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=FakeSession()):
        await coordinator.async_refresh()
        card = await coordinator.async_frames_for_card()
    assert coordinator.last_update_success is False
    assert "no radar frame for the last 15 minutes" in caplog.text
    assert coordinator.data is None and coordinator.fresh is False
    assert coordinator.latest_png() is None
    assert card["frames"] == [] and card["newest"] is None and card["motion_kmh"] is None


async def test_failed_reads_keep_the_last_frame_for_a_while(hass: HomeAssistant, swiss_now, no_wait, freezer, caplog) -> None:
    session = served(T, T - 5 * MINUTES)
    coordinator = RadarCoordinator(hass, make_entry(hass))
    message = "Radar frame not read, keeping the last one"
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)

        session.routes[frame_url(T + 10 * MINUTES)] = FakeResponse(500)
        freezer.move_to(T + 11 * MINUTES)
        await coordinator.async_refresh()
        assert coordinator.last_update_success and coordinator.data.frame_ts == T
        assert f"{message}: radar answered 500" in caplog.text

        # warned once, not at every further failure
        session.routes[frame_url(T + 15 * MINUTES)] = aiohttp.ClientError("connection lost")
        freezer.move_to(T + 16 * MINUTES)
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert caplog.text.count(message) == 1

        # a good frame in between, then the next failure is reported again
        session.routes[frame_url(T + 15 * MINUTES)] = radar_file()
        session.routes[frame_url(T + 20 * MINUTES)] = radar_file()
        freezer.move_to(T + 21 * MINUTES)
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert coordinator.data.frame_ts == T + 20 * MINUTES
        session.routes[frame_url(T + 25 * MINUTES)] = FakeResponse(503)
        freezer.move_to(T + 26 * MINUTES)
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert caplog.text.count(message) == 2

        # too old to stand for "now": the entities go unavailable
        session.routes[frame_url(T + 50 * MINUTES)] = TimeoutError()
        freezer.move_to(T + 51 * MINUTES)
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.last_update_success is False
    assert coordinator.fresh is False


async def test_no_newer_frame_for_too_long(hass: HomeAssistant, swiss_now, no_wait, freezer, caplog) -> None:
    session = served(T, T - 5 * MINUTES)
    coordinator = RadarCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
        freezer.move_to(T + 35 * MINUTES)
        await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    assert "newest radar frame is from 10:25 UTC" in caplog.text


async def test_missing_slots_are_forgotten_after_the_history_window(hass: HomeAssistant, swiss_now, no_wait, freezer) -> None:
    later = T + 135 * MINUTES
    session = served(T, T - 5 * MINUTES, later, later - 5 * MINUTES)
    coordinator = RadarCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert T - 60 * MINUTES in coordinator._missing
        freezer.move_to(later + 5 * MINUTES)
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.data.frame_ts == later
    assert T - 60 * MINUTES not in coordinator._missing
    assert [frame.ts for frame in coordinator.frames][-2:] == [later - 5 * MINUTES, later]


async def test_history_runs_once_and_stops_at_an_error(hass: HomeAssistant, swiss_now, caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.swiss_meteo.radar")
    session = served(T, T - 5 * MINUTES, T - 20 * MINUTES)
    session.routes[frame_url(T - 15 * MINUTES)] = aiohttp.ClientError("down")
    coordinator = RadarCoordinator(hass, make_entry(hass))
    gate = asyncio.Event()

    async def wait(_seconds: float) -> None:
        await gate.wait()

    with patch(ASYNCIO, SimpleNamespace(sleep=wait)), patch(SESSION, return_value=session):
        await coordinator.async_refresh()
        await asyncio.sleep(0)
        running = coordinator._backfill
        assert not running.done()
        # the next read does not start a second history run
        await coordinator.async_refresh()
        assert coordinator._backfill is running
        gate.set()
        await hass.async_block_till_done(wait_background_tasks=True)
    assert "Radar history frame" in caplog.text
    # the run ended at the failing slot
    assert frame_url(T - 20 * MINUTES) not in session.urls()
    assert [frame.ts for frame in coordinator.frames] == [T - 5 * MINUTES, T]


async def test_history_without_a_frame_starts_at_the_current_slot(hass: HomeAssistant, swiss_now, no_wait) -> None:
    session = FakeSession()
    coordinator = RadarCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=session):
        await coordinator._fill_history()
    assert len(session.calls) == 23
    assert session.urls()[0] == frame_url(T - 10 * MINUTES)
    assert session.urls()[-1] == frame_url(T - 120 * MINUTES)
