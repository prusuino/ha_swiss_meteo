"""The map of Switzerland: the places' days out of the whole daily files,
the country's warning areas, the national radar picture, and the layers as
the card asks for them — read on demand, kept while current, counted."""
from __future__ import annotations

import base64
import struct
import zlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant

from custom_components.swiss_meteo.meteoalarm import parse_feed
from custom_components.swiss_meteo.national import (
    _R_COL,
    _R_H,
    _R_ROW,
    _R_W,
    PLACES,
    NationalData,
    km,
    national,
    parse_daily,
    render_national,
    warning_areas,
)
from custom_components.swiss_meteo.ogd import OgdUnavailable, forecast_file_url
from custom_components.swiss_meteo.radar import _level, frame_url

from .conftest import NOW, RUN
from .fakes import FakeResponse, FakeSession
from .feeds import setup_everything
from .test_radar import COL, ROW, T, radar_file

SESSION = "custom_components.swiss_meteo.national.async_get_clientsession"
LATEST_RUN = "custom_components.swiss_meteo.national.async_find_latest_run"
MINUTES = timedelta(minutes=1)


def daily_file(param: str, first: float) -> bytes:
    """A daily file with Zürich and Bern, a station that shares Zürich's
    number, a place the map does not show and a row without a value."""
    rows = [f"point_id;point_type_id;Date;{param}"]
    for n, day in enumerate(("202611080000", "202611090000", "202611100000")):
        rows += [
            f"800100;1;{day};99",  # a station with the same number
            f"800100;2;{day};{first + n}",
            f"301100;2;{day};{first + 10 + n}",
            f"123400;2;{day};50",
        ]
    rows.append("120400;2;202611080000;")
    return "\n".join(rows).encode("latin-1")


BODIES = {"jp2000d0": daily_file("jp2000d0", 3), "tre200px": daily_file("tre200px", 8), "tre200pn": daily_file("tre200pn", 1)}


def test_days_of_the_places_out_of_the_daily_files() -> None:
    places = {p["name"]: p for p in parse_daily(BODIES)}
    assert set(places) == {"Zürich", "Bern"}  # the others are not in these files
    zurich = places["Zürich"]
    assert zurich["tier"] == 1
    assert (zurich["e"], zurich["n"]) == km(47.372289, 8.542189)
    assert 2680 < zurich["e"] < 2686 and 1245 < zurich["n"] < 1250  # LV95 kilometres
    assert zurich["days"] == [
        {"date": "2026-11-08", "symbol": 3.0, "high": 8.0, "low": 1.0},
        {"date": "2026-11-09", "symbol": 4.0, "high": 9.0, "low": 2.0},
        {"date": "2026-11-10", "symbol": 5.0, "high": 10.0, "low": 3.0},
    ]
    assert places["Bern"]["days"][0] == {"date": "2026-11-08", "symbol": 13.0, "high": 18.0, "low": 11.0}
    assert parse_daily({"jp2000d0": b"point_id;point_type_id;Date;jp2000d0\n"}) == []


def test_the_map_has_main_places_and_more_for_the_zoom() -> None:
    assert len({p.point_id for p in PLACES}) == len(PLACES)
    assert sum(p.tier == 1 for p in PLACES) >= 10 and any(p.tier == 2 for p in PLACES)


SQUARE = "46.9,7.3 46.9,7.6 47.1,7.6 47.1,7.3 46.9,7.3"


def feed_entry(identifier: str, title: str, *, expires: str = "2026-11-09T06:00:00+00:00", status: str = "Actual", kind: str = "Alert", polygon: str | None = SQUARE) -> str:
    area = f"<cap:polygon>{polygon}</cap:polygon>" if polygon else ""
    return (
        f"<entry>{area}<cap:areaDesc>Bern</cap:areaDesc><cap:onset>2026-11-08T18:00:00+00:00</cap:onset>"
        f"<cap:expires>{expires}</cap:expires><cap:message_type>{kind}</cap:message_type><cap:status>{status}</cap:status>"
        f"<cap:identifier>{identifier}</cap:identifier><title>{title}</title></entry>"
    )


def feed(*entries: str) -> bytes:
    return (
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">'
        + "".join(entries)
        + "</feed>"
    ).encode()


def test_warning_areas_of_the_country() -> None:
    entries = parse_feed(
        feed(
            feed_entry("red", "Red Wind Warning issued for Switzerland - Bern"),
            feed_entry("yellow", "Yellow Snow-ice Warning issued for Switzerland - Bern"),
            feed_entry("over", "Orange Rain Warning issued for Switzerland - Bern", expires="2026-11-08T09:00:00+00:00"),
            feed_entry("cancelled", "Orange Rain Warning issued for Switzerland - Bern", kind="Cancel"),
            feed_entry("exercise", "Orange Rain Warning issued for Switzerland - Bern", status="Exercise"),
            feed_entry("nowhere", "Orange Rain Warning issued for Switzerland - Bern", polygon=None),
            feed_entry("unnamed", "Something else for Bern"),
        )
    )
    assert [(e.identifier, e.level, e.kind) for e in entries[:2]] == [("red", "red", "wind"), ("yellow", "yellow", "snow-ice")]
    assert entries[-1].level == ""  # a title of another kind: not drawn
    areas = warning_areas(entries, NOW)
    assert [(a["level"], a["kind"]) for a in areas] == [("yellow", "snow-ice"), ("red", "wind")]  # the strongest is drawn last
    red = areas[1]
    assert red["area"] == "Bern"
    assert red["onset"] == "2026-11-08T18:00:00+00:00" and red["expires"] == "2026-11-09T06:00:00+00:00"
    (ring,) = red["rings"]
    assert len(ring) == 5 and ring[0] == ring[-1]
    assert all(2580 < e < 2625 and 1190 < n < 1220 for e, n in ring)  # LV95 kilometres around Bern
    # a ring that collapses on the 200 m grid is left out
    tiny = parse_feed(feed(feed_entry("tiny", "Yellow Rain Warning issued", polygon="46.9,7.3 46.9001,7.3001 46.9,7.3001 46.9,7.3")))
    assert warning_areas(tiny, NOW)[0]["rings"] == []


def picture(png_b64: str) -> list[bytes]:
    png = base64.b64decode(png_b64)
    position, chunks = 8, {}
    while position < len(png):
        (length,) = struct.unpack(">I", png[position : position + 4])
        chunks[png[position + 4 : position + 8]] = png[position + 8 : position + 8 + length]
        position += 12 + length
    width, height = struct.unpack(">II", chunks[b"IHDR"][:8])
    assert (width, height) == (_R_W, _R_H)
    raw = zlib.decompress(chunks[b"IDAT"])
    return [raw[y * (width + 1) + 1 : (y + 1) * (width + 1)] for y in range(height)]


def test_radar_picture_of_the_country() -> None:
    rows = picture(render_national(radar_file()))
    # the rain at Zürich is where Zürich is on the map; nothing else is drawn
    assert rows[ROW - _R_ROW][COL - _R_COL] == _level(1.5)
    assert sum(1 for row in rows for value in row if value) == 1


def forecast_session(run: datetime = RUN) -> FakeSession:
    return FakeSession({forecast_file_url(run, param): body for param, body in BODIES.items()})


async def test_forecast_is_read_when_asked_and_kept(hass: HomeAssistant, swiss_now, freezer) -> None:
    data = NationalData(hass)
    traffic: list[tuple[int, int]] = []

    def account(requests: int, nbytes: int) -> None:
        traffic.append((requests, nbytes))

    session = forecast_session()
    with patch(SESSION, return_value=session), patch(LATEST_RUN, AsyncMock(return_value=RUN)) as latest:
        first = await data.async_forecast(account)
        assert first["run"] == RUN.isoformat()
        assert {p["name"] for p in first["places"]} == {"Zürich", "Bern"}
        assert len(session.calls) == 3
        assert traffic == [(1, len(body)) for body in BODIES.values()]

        # a second card, minutes later: nothing is read
        freezer.tick(timedelta(minutes=30))
        assert await data.async_forecast(account) == first
        assert len(session.calls) == 3 and latest.await_count == 1

        # after three hours it is read again
        freezer.tick(timedelta(hours=3))
        await data.async_forecast(account)
        assert len(session.calls) == 6

        # on the next day yesterday is gone, and the files are read again
        freezer.move_to(datetime(2026, 11, 9, 0, 30, tzinfo=UTC))
        tomorrow = await data.async_forecast(account)
        assert len(session.calls) == 9
        assert [d["date"] for d in tomorrow["places"][0]["days"]] == ["2026-11-09", "2026-11-10"]


async def test_forecast_failures_are_not_retried_at_once(hass: HomeAssistant, swiss_now, freezer) -> None:
    data = NationalData(hass)
    with patch(SESSION, return_value=FakeSession()), patch(LATEST_RUN, AsyncMock(return_value=RUN)) as latest:
        assert await data.async_forecast() == {"run": None, "places": []}  # the files are not there
        assert await data.async_forecast() == {"run": None, "places": []}
        assert latest.await_count == 1  # the second card does not ask again
        freezer.tick(timedelta(minutes=11))
        await data.async_forecast()
        assert latest.await_count == 2
    with patch(SESSION, return_value=forecast_session()), patch(LATEST_RUN, AsyncMock(return_value=None)):
        freezer.tick(timedelta(minutes=11))
        assert (await data.async_forecast())["places"] == []  # no run published
    with patch(SESSION, return_value=forecast_session()), patch(LATEST_RUN, AsyncMock(return_value=RUN)):
        freezer.tick(timedelta(minutes=11))
        assert len((await data.async_forecast())["places"]) == 2

    # what was read stays on the map through an outage, for half a day
    with patch(SESSION, return_value=FakeSession()), patch(LATEST_RUN, AsyncMock(side_effect=OgdUnavailable("down"))):
        freezer.tick(timedelta(hours=4))
        assert len((await data.async_forecast())["places"]) == 2
        freezer.tick(timedelta(hours=9))
        assert await data.async_forecast() == {"run": None, "places": []}


async def test_radar_frames_of_the_last_hour(hass: HomeAssistant, swiss_now, freezer) -> None:
    freezer.move_to(T + 2 * MINUTES)
    data = NationalData(hass)
    traffic: list[tuple[int, int]] = []
    # the newest slot is not published yet; the hour before it is, down to a gap
    session = FakeSession({frame_url(T - 5 * n * MINUTES): radar_file() for n in (1, 2, 3)})
    with patch(SESSION, return_value=session):
        radar = await data.async_radar(lambda requests, nbytes: traffic.append((requests, nbytes)))
        assert [frame["ts"] for frame in radar["frames"]] == [(T - 5 * n * MINUTES).isoformat() for n in (3, 2, 1)]
        assert radar["size"] == {"w": _R_W, "h": _R_H} and radar["origin"] == {"e": 2475, "n": 1305}
        assert len(radar["levels"]) + 1 == len(radar["palette"])
        assert len(session.calls) == 5  # stops at the first gap in the past
        assert traffic == [(1, len(radar_file()))] * 3

        # another card a moment later reads nothing; a minute later only what is missing
        await data.async_radar()
        assert len(session.calls) == 5
        session.routes[frame_url(T)] = radar_file()
        freezer.tick(timedelta(minutes=1))
        assert len((await data.async_radar())["frames"]) == 4
        assert session.urls("GET")[5] == frame_url(T)

        # frames older than an hour leave the loop
        freezer.tick(timedelta(minutes=60))
        assert [frame["ts"] for frame in (await data.async_radar())["frames"]] == [T.isoformat()]


async def test_a_radar_frame_that_cannot_be_read(hass: HomeAssistant, swiss_now, freezer) -> None:
    freezer.move_to(T + 2 * MINUTES)
    session = FakeSession({frame_url(T): b"not a radar file", frame_url(T - 5 * MINUTES): FakeResponse(500)})
    with patch(SESSION, return_value=session):
        assert (await NationalData(hass).async_radar())["frames"] == []


# --- the layers as the card asks for them --------------------------------------


async def ask(hass: HomeAssistant, hass_ws_client, layer: str) -> dict:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "swiss_meteo/map", "layer": layer})
    return await client.receive_json()


async def test_layers_for_the_card(hass: HomeAssistant, setup_integration, hass_ws_client) -> None:
    entry = await setup_everything(hass, setup_integration)
    assert national(hass) is national(hass)

    answer = await ask(hass, hass_ws_client, "warnings")
    assert answer["success"] is True
    assert answer["result"]["enabled"] is True and answer["result"]["available"] is True
    assert isinstance(answer["result"]["warnings"], list)

    before = entry.runtime_data.forecast.data.requests_today
    with patch(SESSION, return_value=forecast_session()), patch(LATEST_RUN, AsyncMock(return_value=RUN)):
        answer = await ask(hass, hass_ws_client, "weather")
    assert answer["success"] is True and len(answer["result"]["places"]) == 2
    # what the map read is part of the entry's traffic
    assert entry.runtime_data.forecast.data.requests_today == before + 3

    with patch(SESSION, return_value=FakeSession()):
        answer = await ask(hass, hass_ws_client, "radar")
    assert answer["success"] is True and answer["result"]["frames"] == []

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "swiss_meteo/map", "layer": "something"})
    assert (await client.receive_json())["success"] is False


async def test_warning_layer_without_the_warnings(hass: HomeAssistant, setup_integration, hass_ws_client) -> None:
    await setup_integration()  # warnings switched off
    answer = await ask(hass, hass_ws_client, "warnings")
    assert answer["result"] == {"enabled": False, "available": False, "warnings": []}


async def test_no_layer_without_a_loaded_entry(hass: HomeAssistant, setup_integration, hass_ws_client) -> None:
    entry = await setup_integration()
    await hass.config_entries.async_unload(entry.entry_id)
    answer = await ask(hass, hass_ws_client, "weather")
    assert answer["success"] is False and answer["error"]["code"] == "not_found"
