"""What the small feeds cost is counted too, and a warnings or radar outage
is worth a word under Repairs."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.swiss_meteo import ogd
from custom_components.swiss_meteo.const import DOMAIN
from custom_components.swiss_meteo.coordinator import StationCoordinator
from custom_components.swiss_meteo.meteoalarm import WARNINGS_URL, WarningsCoordinator
from custom_components.swiss_meteo.open_meteo import API_URL, OpenMeteoCoordinator
from custom_components.swiss_meteo.pollen import PollenCoordinator
from custom_components.swiss_meteo.radar import RadarCoordinator
from custom_components.swiss_meteo.traffic import metered, note, transferred

from .conftest import ENTRY_ID, make_entry
from .fakes import FakeResponse, FakeSession
from .test_meteoalarm import SESSION as WARNINGS_SESSION
from .test_meteoalarm import TWO_WARNINGS
from .test_radar import MINUTES, T, frame_url, no_wait, radar_file, served  # noqa: F401 (no_wait is a fixture)
from .test_radar import SESSION as RADAR_SESSION
from .warnfeed import warning_routes

URL = "https://data.geo.admin.ch/some/file.csv"


def issue(hass: HomeAssistant, key: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{key}_{ENTRY_ID}")


class Counter(list):
    """Collects (requests, bytes) as a coordinator's account would."""

    def __call__(self, requests: int, nbytes: int) -> None:
        self.append((requests, nbytes))


def test_nothing_is_counted_outside_a_metered_read() -> None:
    counter = Counter()
    note(1, 100)  # no counter in force: nowhere to go, no error
    with metered(counter):
        note(1, 100)
        with metered(None):  # a read that names no counter counts nothing
            note(1, 50)
        note(2, 30)
    note(1, 7)
    assert counter == [(1, 100), (2, 30)]


def test_transferred_prefers_what_the_server_states() -> None:
    assert transferred({"Content-Length": "1234"}, b"x" * 9000) == 1234  # sent compressed
    assert transferred({}, b"x" * 90) == 90
    assert transferred({"Content-Length": "chunked?"}, b"abc") == 3
    assert transferred(None, b"abcd") == 4


async def test_a_plain_open_data_read_reports_its_size() -> None:
    counter = Counter()
    session = FakeSession({URL: b"a;b\n1;2\n"})
    with metered(counter):
        assert await ogd._fetch(session, URL) == b"a;b\n1;2\n"
        session.routes[URL] = FakeResponse(503)
        with pytest.raises(ogd.OgdUnavailable):
            await ogd._fetch(session, URL)
    # the failed request was made too, it just carried nothing
    assert counter == [(1, 8), (1, 0)]


async def test_station_pollen_and_open_meteo_reads_run_metered(hass: HomeAssistant, swiss_now) -> None:
    """The coordinators name the entry's counter for the time of their read."""
    counter = Counter()

    async def read(*_args, **_kwargs):
        note(1, 4321)
        return "reading"

    entry = make_entry(hass, {"station": "SMA", "pollen_station": "PZH"})
    station = StationCoordinator(hass, entry, counter)
    with patch("custom_components.swiss_meteo.coordinator.async_fetch_station_reading", read):
        await station.async_refresh()
    pollen = PollenCoordinator(hass, entry, counter)
    with patch("custom_components.swiss_meteo.pollen.async_fetch_pollen_reading", read):
        await pollen.async_refresh()
    open_meteo = OpenMeteoCoordinator(hass, entry, counter)
    with patch("custom_components.swiss_meteo.open_meteo.async_fetch_open_meteo", read):
        await open_meteo.async_refresh()
    assert counter == [(1, 4321)] * 3
    # without a counter the same reads simply are not counted
    with patch("custom_components.swiss_meteo.coordinator.async_fetch_station_reading", read):
        await StationCoordinator(hass, entry).async_refresh()
    assert len(counter) == 3


async def test_the_open_meteo_request_reports_its_size() -> None:
    from custom_components.swiss_meteo.open_meteo import OpenMeteoError, async_fetch_open_meteo

    counter = Counter()

    class Session:
        def __init__(self, response) -> None:
            self.response = response

        def get(self, url, **_kwargs):
            assert url == API_URL
            return self.response

    payload = {"hourly": {"time": []}}
    with metered(counter), patch("custom_components.swiss_meteo.open_meteo.parse_open_meteo", return_value="parsed"):
        answer = FakeResponse(payload=payload, body=b"x" * 700, headers={"Content-Length": "210"})
        assert await async_fetch_open_meteo(Session(answer), 47.0, 8.0) == "parsed"
        with pytest.raises(OpenMeteoError):
            await async_fetch_open_meteo(Session(FakeResponse(429)), 47.0, 8.0)
    assert counter == [(1, 210), (1, 0)]


async def test_warnings_are_counted_and_an_hour_without_them_is_reported(hass: HomeAssistant, swiss_now) -> None:
    counter = Counter()
    routes = warning_routes(TWO_WARNINGS)
    session = FakeSession(routes)
    coordinator = WarningsCoordinator(hass, make_entry(hass), counter)
    with patch(WARNINGS_SESSION, return_value=session):
        await coordinator.async_refresh()
        # the feed and the two alerts that cover the point, each with its size
        assert counter == [(1, len(body)) for body in routes.values()]
        del counter[:]

        session.routes[WARNINGS_URL] = FakeResponse(503)
        for _ in range(5):
            await coordinator.async_refresh()
        # five failed reads: the last list is still shown, nothing to report yet
        assert coordinator.last_update_success and issue(hass, "warnings_unreachable") is None
        session.routes[WARNINGS_URL] = aiohttp.ClientError("down")
        await coordinator.async_refresh()
        notice = issue(hass, "warnings_unreachable")
        assert notice is not None and notice.translation_placeholders == {"error": "down"}
        # the refused requests were made as well; the one that never arrived was not
        assert counter == [(1, 0)] * 5

        session.routes.update(warning_routes({"warnings": []}))
        await coordinator.async_refresh()
        assert issue(hass, "warnings_unreachable") is None and coordinator.data.items == []

    # without a counter the feed is read all the same
    with patch(WARNINGS_SESSION, return_value=FakeSession(warning_routes(TWO_WARNINGS))):
        plain = WarningsCoordinator(hass, make_entry(hass))
        await plain.async_refresh()
    assert plain.last_update_success and len(plain.data.items) == 2


async def test_half_an_hour_without_radar_is_reported(hass: HomeAssistant, swiss_now, no_wait, freezer) -> None:
    session = served(T, T - 5 * MINUTES)
    coordinator = RadarCoordinator(hass, make_entry(hass))
    with patch(RADAR_SESSION, return_value=session):
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert issue(hass, "radar_unreachable") is None

        for step in range(1, 7):
            session.routes[frame_url(T + 5 * step * MINUTES)] = FakeResponse(500)
            freezer.move_to(T + (5 * step + 1) * MINUTES)
            await coordinator.async_refresh()
            assert (issue(hass, "radar_unreachable") is not None) is (step == 6)

        # a frame again: the notice goes
        newest = T + 35 * MINUTES
        session.routes[frame_url(newest)] = radar_file()
        session.routes[frame_url(newest - 5 * MINUTES)] = radar_file()
        freezer.move_to(newest + timedelta(minutes=1))
        await coordinator.async_refresh()
        await hass.async_block_till_done(wait_background_tasks=True)
        assert coordinator.last_update_success and issue(hass, "radar_unreachable") is None
