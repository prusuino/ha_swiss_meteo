"""The official warnings: reading the alert feed, finding the alerts that
cover a point, and the coordinator against a feed served from memory."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import aiohttp
import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant

from custom_components.swiss_meteo.meteoalarm import (
    WARNINGS_URL,
    WarningsCoordinator,
    WarningsData,
    _code,
    _param,
    _parse_time,
    _pick_info,
    _polygons,
    parse_polygon,
    parse_warnings,
    point_in_ring,
)

from .conftest import NOW, make_entry
from .fakes import FakeResponse, FakeSession

SESSION = "custom_components.swiss_meteo.meteoalarm.async_get_clientsession"

LAT, LON = 47.3769, 8.5417
AROUND = "47.0,8.0 47.0,9.0 48.0,9.0 48.0,8.0 47.0,8.0"
ELSEWHERE = "46.0,6.0 46.0,6.5 46.5,6.5 46.5,6.0 46.0,6.0"
EVENING = datetime(2026, 11, 8, 18, 30, tzinfo=UTC)


def info(
    *,
    language: str = "en-GB",
    level: str | None = "2; yellow; Moderate",
    kind: str | None = "1; Wind",
    onset: str | None = "2026-11-08T08:00:00+00:00",
    expires: str | None = "2026-11-08T20:00:00+00:00",
    polygon: Any = AROUND,
    **extra: Any,
) -> dict[str, Any]:
    """One language block of an alert."""
    parameters = []
    if level is not None:
        parameters.append({"valueName": "awareness_level", "value": level})
    if kind is not None:
        parameters.append({"valueName": "awareness_type", "value": kind})
    block = {
        "language": language,
        "event": "Wind warning",
        "headline": "Strong wind",
        "description": "Gusts up to 90 km/h.",
        "instruction": "Secure loose objects.",
        "senderName": "MeteoSwiss",
        "web": "https://www.meteoswiss.admin.ch",
        "onset": onset,
        "expires": expires,
        "parameter": parameters,
        "area": [{"areaDesc": "Zürich", "polygon": polygon}],
    }
    block.update(extra)
    return block


def alert(identifier: str | None, *infos: dict[str, Any], msg_type: str = "Alert", status: str = "Actual", references: str | None = None) -> dict[str, Any]:
    """One entry of the feed."""
    body: dict[str, Any] = {
        "identifier": identifier,
        "sender": "sender@example.ch",
        "sent": "2026-11-08T07:55:00+00:00",
        "status": status,
        "msgType": msg_type,
        "info": list(infos) or [info()],
    }
    if references:
        body["references"] = references
    return {"uuid": f"uuid-{identifier}", "alert": body}


LATER = info(level="4; red; Extreme", kind="10; Rain", onset="2026-11-08T18:00:00+00:00", expires="2026-11-09T06:00:00+00:00")
TWO_WARNINGS = {"warnings": [alert("now"), alert("later", LATER)]}


# --- reading the pieces ------------------------------------------------------


def test_times_are_read_as_utc_when_they_name_no_zone() -> None:
    assert _parse_time(None) is None
    assert _parse_time(5) is None
    assert _parse_time("soon") is None
    assert _parse_time("2026-11-08T09:00:00Z") == datetime(2026, 11, 8, 9, tzinfo=UTC)
    assert _parse_time("2026-11-08T09:00:00") == datetime(2026, 11, 8, 9, tzinfo=UTC)
    assert _parse_time("2026-11-08T09:00:00+01:00") == datetime(2026, 11, 8, 8, tzinfo=UTC)


def test_polygon_text_and_point_in_ring() -> None:
    assert parse_polygon("47.0,8.0 north,east 47.0,9.0 1,2,3") == [(47.0, 8.0), (47.0, 9.0)]
    ring = parse_polygon(AROUND)
    assert len(ring) == 5
    assert point_in_ring(LAT, LON, ring) is True
    assert point_in_ring(46.2, 6.1, ring) is False
    assert point_in_ring(47.5, 9.5, ring) is False
    assert point_in_ring(LAT, LON, ring[:2]) is False


def test_parameters_and_their_codes() -> None:
    block = {"parameter": ["junk", {"valueName": "awareness_level", "value": "3; orange; Severe"}]}
    assert _param(block, "awareness_level") == "3; orange; Severe"
    assert _param(block, "awareness_type") is None
    assert _param({}, "awareness_level") is None
    assert _code("3; orange; Severe") == 3
    assert _code("severe") is None
    assert _code("") is None
    assert _code(None) is None


def test_language_block_falls_back_to_english_then_to_the_first() -> None:
    german, english, french = {"language": "de-DE"}, {"language": "en-GB"}, {"language": "fr-FR"}
    assert _pick_info([german, english, french], "fr") is french
    assert _pick_info([german, english, french], "it") is english
    assert _pick_info([german, english], "") is english
    assert _pick_info([german, french], "it") is german


def test_polygons_of_an_info_block() -> None:
    block = {"area": ["junk", {"areaDesc": "no outline"}, {"polygon": [AROUND, "47.0,8.0 47.0,9.0"]}, {"polygon": ELSEWHERE}]}
    rings = _polygons(block)
    assert len(rings) == 2  # the line with two points is no area
    assert rings[1][0] == (46.0, 6.0)
    assert _polygons({}) == []


# --- the feed ----------------------------------------------------------------


def test_only_the_valid_alerts_covering_the_point() -> None:
    payload = {
        "warnings": [
            "junk",
            {"uuid": "no-alert"},
            {"uuid": "empty", "alert": {"identifier": "empty", "info": ["junk"]}},
            alert("cancelled", msg_type="Cancel"),
            alert("exercise", status="Exercise"),
            alert("old"),
            alert("new", info(level="3; orange; Severe"), msg_type="Update", references="sender@example.ch,old,2026-11-08T07:55:00+00:00 broken"),
            alert("new", info(level="4; red; Extreme")),
            alert("expired", info(expires="2026-11-08T10:30:00+00:00")),
            alert("nowhere", info(polygon=None)),
            alert("elsewhere", info(polygon=ELSEWHERE)),
            alert("green", info(level="1; green; Minor")),
            alert("odd", info(level="high")),
            alert("later", LATER),
        ]
    }
    data = parse_warnings(payload, LAT, LON, "en", NOW)
    assert data.fetched == NOW
    assert data.total == 11  # every alert with an info block, the whole country
    assert data.unlocated == 1
    # in force first; the replaced alert and the repeated one are gone
    assert [(item.identifier, item.level, item.upcoming) for item in data.items] == [("new", "orange", False), ("later", "red", True)]

    new = data.items[0]
    assert (new.level_code, new.type_key, new.type_code) == (3, "wind", 1)
    assert (new.event, new.headline) == ("Wind warning", "Strong wind")
    assert (new.description, new.instruction) == ("Gusts up to 90 km/h.", "Secure loose objects.")
    assert new.onset == datetime(2026, 11, 8, 8, tzinfo=UTC)
    assert new.expires == datetime(2026, 11, 8, 20, tzinfo=UTC)
    assert new.sent == datetime(2026, 11, 8, 7, 55, tzinfo=UTC)
    assert new.areas == ["Zürich"]
    assert (new.sender, new.web, new.language) == ("MeteoSwiss", "https://www.meteoswiss.admin.ch", "en-GB")
    assert (data.items[1].type_key, data.items[1].type_code) == ("rain", 10)


def test_empty_feed() -> None:
    data = parse_warnings({}, LAT, LON, "en", NOW)
    assert (data.items, data.total, data.unlocated) == ([], 0, 0)


def test_what_an_alert_leaves_out() -> None:
    sparse = info(
        level=None,
        kind=None,
        onset=None,
        expires=None,
        effective="2026-11-08T09:00:00Z",
        description="d" * 700,
        instruction="i" * 500,
        senderName=None,
        area=[{"areaDesc": " Zürich ", "polygon": [AROUND]}, {"polygon": ELSEWHERE}, "junk"],
    )
    payload = {"warnings": [alert(None, sparse), alert("violet", info(level="5; violet", kind="99; Unknown"))]}
    data = parse_warnings(payload, LAT, LON, "en", NOW)
    first = next(item for item in data.items if item.identifier == "uuid-None")
    # no level: the lowest colour; the start of validity stands in for the onset
    assert (first.level, first.level_code) == ("yellow", 2)
    assert (first.type_key, first.type_code) == ("other", None)
    assert first.onset == datetime(2026, 11, 8, 9, tzinfo=UTC)
    assert first.expires is None
    assert (len(first.description), len(first.instruction)) == (600, 400)
    assert first.sender == "sender@example.ch"
    assert first.areas == ["Zürich"]
    assert first.as_dict()["expires"] is None

    violet = next(item for item in data.items if item.identifier == "violet")
    assert (violet.level, violet.level_code) == ("red", 5)  # above the known colours
    assert (violet.type_key, violet.type_code) == ("other", 99)


def test_area_is_taken_from_another_language_block() -> None:
    german = info(language="de-DE", headline="Starker Wind", polygon=None)
    french = info(language="fr-FR", headline="Vent fort")
    data = parse_warnings({"warnings": [alert("bilingual", german, french)]}, LAT, LON, "de", NOW)
    (item,) = data.items
    assert (item.headline, item.language) == ("Starker Wind", "de-DE")
    assert data.unlocated == 0


@freeze_time(NOW)
def test_level_and_lists_follow_the_clock() -> None:
    data = parse_warnings(TWO_WARNINGS, LAT, LON, "en", NOW)
    assert data.level() == "yellow"
    assert [item.identifier for item in data.active] == ["now"]
    assert [item.identifier for item in data.upcoming] == ["later"]
    assert data.as_list(brief=True) == [
        {
            "event": "Wind warning",
            "level": "yellow",
            "type": "wind",
            "headline": "Strong wind",
            "onset": "2026-11-08T08:00:00+00:00",
            "expires": "2026-11-08T20:00:00+00:00",
            "areas": ["Zürich"],
            "upcoming": False,
            "web": "https://www.meteoswiss.admin.ch",
        },
        {
            "event": "Wind warning",
            "level": "red",
            "type": "rain",
            "headline": "Strong wind",
            "onset": "2026-11-08T18:00:00+00:00",
            "expires": "2026-11-09T06:00:00+00:00",
            "areas": ["Zürich"],
            "upcoming": True,
            "web": "https://www.meteoswiss.admin.ch",
        },
    ]
    full = data.as_list()
    assert (full[0]["description"], full[0]["instruction"]) == ("Gusts up to 90 km/h.", "Secure loose objects.")
    # without a clock the state at reading time is given
    assert data.items[1].as_dict()["upcoming"] is True

    with freeze_time(EVENING):
        # the announced warning has started: it counts, and leads the list
        assert data.level() == "red"
        assert data.upcoming == []
        assert [entry["level"] for entry in data.as_list(brief=True)] == ["red", "yellow"]
        assert data.as_list(brief=True)[0]["upcoming"] is False

    assert WarningsData(fetched=NOW).level() == "none"


@freeze_time(NOW)
def test_lists_are_capped_at_ten() -> None:
    wide = info(area=[{"areaDesc": f"Area {number}", "polygon": AROUND} for number in range(12)])
    payload = {"warnings": [alert(f"alert-{number}", wide) for number in range(12)]}
    data = parse_warnings(payload, LAT, LON, "en", NOW)
    assert len(data.items) == 12
    listed = data.as_list()
    assert len(listed) == 10
    assert listed[0]["areas"] == [f"Area {number}" for number in range(10)]


# --- coordinator -------------------------------------------------------------


async def test_first_read(hass: HomeAssistant, swiss_now) -> None:
    session = FakeSession({WARNINGS_URL: FakeResponse(payload=TWO_WARNINGS)})
    coordinator = WarningsCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
    assert coordinator.last_update_success and coordinator.fresh
    assert coordinator.data.level() == "yellow"
    assert coordinator.data.fetched == NOW
    assert [item.identifier for item in coordinator.data.items] == ["now", "later"]
    _method, url, headers = session.calls[0]
    assert url == WARNINGS_URL
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"].startswith("SwissMeteo/")


async def test_texts_in_the_language_of_the_instance(hass: HomeAssistant, swiss_now) -> None:
    hass.config.language = "de"
    payload = {"warnings": [alert("bilingual", info(), info(language="de-DE", headline="Starker Wind"))]}
    coordinator = WarningsCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=FakeSession({WARNINGS_URL: FakeResponse(payload=payload)})):
        await coordinator.async_refresh()
    assert coordinator.data.items[0].headline == "Starker Wind"


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (FakeResponse(503), "MeteoAlarm answered 503"),
        (FakeResponse(payload=["no", "object"]), "MeteoAlarm feed is not a JSON object"),
        (FakeResponse(payload=ValueError("not JSON at all")), "not JSON at all"),
        (aiohttp.ClientError("connection lost"), "connection lost"),
    ],
)
async def test_first_read_fails(hass: HomeAssistant, swiss_now, caplog, answer: Any, message: str) -> None:
    coordinator = WarningsCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=FakeSession({WARNINGS_URL: answer})):
        await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    assert coordinator.data is None and coordinator.fresh is False
    assert message in caplog.text


async def test_failed_reads_keep_the_last_list_for_two_hours(hass: HomeAssistant, swiss_now, freezer, caplog) -> None:
    session = FakeSession({WARNINGS_URL: FakeResponse(payload=TWO_WARNINGS)})
    coordinator = WarningsCoordinator(hass, make_entry(hass))
    message = "Warnings feed not read, keeping the last list"
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
        first = coordinator.data

        for answer in (FakeResponse(503), FakeResponse(payload=[]), aiohttp.ClientError("down"), TimeoutError()):
            session.routes[WARNINGS_URL] = answer
            await coordinator.async_refresh()
            assert coordinator.last_update_success
            assert coordinator.data is first
        # said once, not at every failed read
        assert caplog.text.count(message) == 1
        assert f"{message}: MeteoAlarm answered 503" in caplog.text

        # a good read in between: the next failure is reported again
        freezer.move_to(NOW + timedelta(minutes=30))
        session.routes[WARNINGS_URL] = FakeResponse(payload={"warnings": []})
        await coordinator.async_refresh()
        assert coordinator.data is not first and coordinator.data.items == []
        session.routes[WARNINGS_URL] = FakeResponse(500)
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert caplog.text.count(message) == 2

        # after two hours without a read the list is no longer shown as current
        freezer.move_to(NOW + timedelta(hours=2, minutes=31))
        await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    assert coordinator.fresh is False
