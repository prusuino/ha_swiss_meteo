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

from homeassistant.util import dt as dt_util

from custom_components.swiss_meteo.meteoalarm import (
    WARNINGS_URL,
    WarningsCoordinator,
    WarningsData,
    WarningsError,
    covering,
    parse_cap,
    parse_feed,
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
from .warnfeed import atom_feed, cap_url, cap_xml, warning_routes

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


# --- the feed and the single alert -------------------------------------------


def test_feed_entries() -> None:
    quiet = info(polygon=None)
    payload = {
        "warnings": [
            alert("now"),
            alert("later", LATER),
            alert("cancelled", msg_type="Cancel"),
            alert("exercise", status="Exercise"),
            alert("nowhere", quiet),
            alert(None),
        ]
    }
    entries = parse_feed(atom_feed(payload))
    # an entry without an identifier cannot be read in full and is left out
    assert [entry.identifier for entry in entries] == ["now", "later", "cancelled", "exercise", "nowhere"]
    now, later, cancelled, exercise, nowhere = entries
    assert now.cap_url == cap_url(payload["warnings"][0]) and now.actual
    assert now.expires == datetime(2026, 11, 8, 20, tzinfo=UTC)
    assert len(now.rings) == 1 and len(now.rings[0]) == 5
    assert later.expires == datetime(2026, 11, 9, 6, tzinfo=UTC)
    assert cancelled.actual is False and exercise.actual is False
    assert nowhere.rings == [] and nowhere.actual

    morning = datetime(2026, 11, 8, 10, 30, tzinfo=UTC)
    assert [entry.identifier for entry in covering(entries, LAT, LON, morning)] == ["now", "later"]
    assert covering(entries, 46.2, 6.2, morning) == []  # Geneva: outside the area
    night = datetime(2026, 11, 8, 21, tzinfo=UTC)
    assert [entry.identifier for entry in covering(entries, LAT, LON, night)] == ["later"]


def test_feed_without_alert_links_and_with_a_short_polygon() -> None:
    payload = {"warnings": [alert("thin", info(polygon="47.0,8.0 48.0,9.0"))]}
    (entry,) = parse_feed(atom_feed(payload, links=False))
    assert entry.cap_url == "" and entry.rings == []


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"{}", "MeteoAlarm feed is not XML"),
        (b"<rss/>", "MeteoAlarm feed is not an Atom feed"),
    ],
)
def test_what_is_not_a_feed(body: bytes, message: str) -> None:
    with pytest.raises(WarningsError, match=message):
        parse_feed(body)


def test_alert_document_reads_like_the_feed_entry() -> None:
    german = info(language="de-DE", headline="Starker Wind", polygon=[AROUND, ELSEWHERE])
    entry = alert("both", info(), german, references="sender,old,2026-11-08T06:00:00+00:00")
    read = parse_cap(cap_xml(entry))
    assert read["identifier"] == "both" and read["msgType"] == "Alert" and read["status"] == "Actual"
    assert read["references"].split(",")[1] == "old"
    assert [block["language"] for block in read["info"]] == ["en-GB", "de-DE"]
    assert read["info"][1]["area"] == [{"areaDesc": "Zürich", "polygon": [AROUND, ELSEWHERE]}]
    assert read["info"][0]["parameter"] == [
        {"valueName": "awareness_level", "value": "2; yellow; Moderate"},
        {"valueName": "awareness_type", "value": "1; Wind"},
    ]
    # read back through the alert parser it is the same warning as from the mapping itself
    at = datetime(2026, 11, 8, 10, 30, tzinfo=UTC)
    for language in ("en", "de"):
        direct = parse_warnings({"warnings": [entry]}, LAT, LON, language, at).items
        through = parse_warnings({"warnings": [{"alert": read}]}, LAT, LON, language, at).items
        assert [item.as_dict(at) for item in through] == [item.as_dict(at) for item in direct]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"not xml at all", "MeteoAlarm alert is not XML"),
        (b"<feed/>", "MeteoAlarm alert is not a CAP alert"),
    ],
)
def test_what_is_not_an_alert(body: bytes, message: str) -> None:
    with pytest.raises(WarningsError, match=message):
        parse_cap(body)


# --- coordinator -------------------------------------------------------------


def requests(session: FakeSession) -> list[tuple[str, str]]:
    """What was asked, as (method, last part of the URL)."""
    return [(method, url.rsplit("/", 1)[-1]) for method, url, _headers in session.calls]


async def test_first_read(hass: HomeAssistant, swiss_now) -> None:
    session = FakeSession(warning_routes(TWO_WARNINGS))
    coordinator = WarningsCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
    assert coordinator.last_update_success and coordinator.fresh
    assert coordinator.data.level() == "yellow"
    assert coordinator.data.fetched == NOW
    assert [item.identifier for item in coordinator.data.items] == ["now", "later"]
    assert (coordinator.data.total, coordinator.data.unlocated) == (2, 0)
    # the feed, then the two alerts that cover the point
    assert requests(session) == [("GET", "meteoalarm-legacy-atom-switzerland"), ("GET", "uuid-now"), ("GET", "uuid-later")]
    _method, url, headers = session.calls[0]
    assert url == WARNINGS_URL
    assert headers["User-Agent"].startswith("SwissMeteo/")
    assert "Accept" not in headers  # asked for XML by name, the server answers with something else


async def test_texts_in_the_language_of_the_instance(hass: HomeAssistant, swiss_now) -> None:
    hass.config.language = "de"
    payload = {"warnings": [alert("bilingual", info(), info(language="de-DE", headline="Starker Wind"))]}
    coordinator = WarningsCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=FakeSession(warning_routes(payload))):
        await coordinator.async_refresh()
    assert coordinator.data.items[0].headline == "Starker Wind"


async def test_only_what_is_needed_is_read(hass: HomeAssistant, swiss_now, freezer) -> None:
    """The feed is read again when its length changed or after an hour; an
    alert is read in full once, and only if it covers the point."""
    elsewhere = alert("elsewhere", info(polygon=ELSEWHERE))
    nowhere = alert("nowhere", info(polygon=None))
    session = FakeSession(warning_routes({"warnings": [alert("now"), elsewhere, nowhere]}))
    coordinator = WarningsCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
        assert requests(session) == [("GET", "meteoalarm-legacy-atom-switzerland"), ("GET", "uuid-now")]
        assert [item.identifier for item in coordinator.data.items] == ["now"]
        assert (coordinator.data.total, coordinator.data.unlocated) == (3, 1)

        # ten minutes later the feed weighs the same: asked for its length, not read
        session.calls.clear()
        freezer.move_to(NOW + timedelta(minutes=10))
        await coordinator.async_refresh()
        assert requests(session) == [("HEAD", "meteoalarm-legacy-atom-switzerland")]
        assert coordinator.data.fetched == NOW + timedelta(minutes=10)
        assert [item.identifier for item in coordinator.data.items] == ["now"]

        # a new alert changes the length: the feed is read, and only the new alert
        session.calls.clear()
        session.routes.update(warning_routes({"warnings": [alert("now"), alert("later", LATER), elsewhere]}))
        freezer.move_to(NOW + timedelta(minutes=20))
        await coordinator.async_refresh()
        assert requests(session) == [
            ("HEAD", "meteoalarm-legacy-atom-switzerland"),
            ("GET", "meteoalarm-legacy-atom-switzerland"),
            ("GET", "uuid-later"),
        ]
        assert [item.identifier for item in coordinator.data.items] == ["now", "later"]

        # an alert that left the feed is forgotten: back again, it is read again
        session.routes.update(warning_routes({"warnings": [alert("later", LATER), elsewhere]}))
        freezer.move_to(NOW + timedelta(minutes=30))
        await coordinator.async_refresh()
        assert [item.identifier for item in coordinator.data.items] == ["later"]
        session.calls.clear()
        session.routes.update(warning_routes({"warnings": [alert("now"), alert("later", LATER), elsewhere]}))
        freezer.move_to(NOW + timedelta(minutes=40))
        await coordinator.async_refresh()
        assert ("GET", "uuid-now") in requests(session) and ("GET", "uuid-later") not in requests(session)

        # an hour after the last read the feed is read whatever it weighs
        session.calls.clear()
        freezer.move_to(NOW + timedelta(minutes=101))
        await coordinator.async_refresh()
        assert requests(session) == [("GET", "meteoalarm-legacy-atom-switzerland")]


async def test_a_warning_ends_without_a_new_read(hass: HomeAssistant, swiss_now, freezer) -> None:
    session = FakeSession(warning_routes(TWO_WARNINGS))
    coordinator = WarningsCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
        session.calls.clear()
        # 20:10: the first warning has expired, the feed still weighs the same
        freezer.move_to(datetime(2026, 11, 8, 20, 10, tzinfo=UTC))
        coordinator._read_at = dt_util.utcnow()  # read recently enough
        await coordinator.async_refresh()
    assert requests(session) == [("HEAD", "meteoalarm-legacy-atom-switzerland")]
    assert [item.identifier for item in coordinator.data.items] == ["later"]


async def test_a_server_that_states_no_length(hass: HomeAssistant, swiss_now, freezer) -> None:
    """Without a length to compare, the feed is read once an hour."""
    session = FakeSession(warning_routes(TWO_WARNINGS), head_length=False)
    coordinator = WarningsCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
        session.calls.clear()
        freezer.move_to(NOW + timedelta(minutes=10))
        await coordinator.async_refresh()
        assert requests(session) == [("HEAD", "meteoalarm-legacy-atom-switzerland")]
        session.calls.clear()
        freezer.move_to(NOW + timedelta(minutes=61))
        await coordinator.async_refresh()
        assert requests(session) == [("GET", "meteoalarm-legacy-atom-switzerland")]
    assert coordinator.last_update_success


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (FakeResponse(503), "MeteoAlarm answered 503"),
        (b'{"warnings": []}', "MeteoAlarm feed is not XML"),
        (b"<rss/>", "MeteoAlarm feed is not an Atom feed"),
        (atom_feed(TWO_WARNINGS, links=False), "MeteoAlarm feed names no alert document"),
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


async def test_an_alert_that_cannot_be_read_fails_the_read(hass: HomeAssistant, swiss_now, caplog) -> None:
    routes = warning_routes(TWO_WARNINGS)
    routes[cap_url(TWO_WARNINGS["warnings"][1])] = FakeResponse(500)
    coordinator = WarningsCoordinator(hass, make_entry(hass))
    with patch(SESSION, return_value=FakeSession(routes)):
        await coordinator.async_refresh()
    assert coordinator.last_update_success is False and "MeteoAlarm answered 500" in caplog.text


async def test_failed_reads_keep_the_last_list_for_two_hours(hass: HomeAssistant, swiss_now, freezer, caplog) -> None:
    session = FakeSession(warning_routes(TWO_WARNINGS))
    coordinator = WarningsCoordinator(hass, make_entry(hass))
    message = "Warnings feed not read, keeping the last list"
    with patch(SESSION, return_value=session):
        await coordinator.async_refresh()
        first = coordinator.data

        for answer in (FakeResponse(503), b"<feed", aiohttp.ClientError("down"), TimeoutError()):
            session.routes[WARNINGS_URL] = answer
            await coordinator.async_refresh()
            assert coordinator.last_update_success
            assert coordinator.data is first
        # said once, not at every failed read
        assert caplog.text.count(message) == 1
        assert f"{message}: MeteoAlarm answered 503" in caplog.text

        # a good read in between: the next failure is reported again
        freezer.move_to(NOW + timedelta(minutes=30))
        session.routes.update(warning_routes({"warnings": []}))
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
