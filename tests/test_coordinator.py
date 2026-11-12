"""The forecast and station coordinators: when a run is read, what is kept
over an outage, and when the repair notices appear."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from custom_components.swiss_meteo.const import DAILY_PARAMS, DOMAIN, EXTENDED_PARAMS, HOURLY_PARAMS
from custom_components.swiss_meteo.coordinator import ForecastCoordinator, ForecastSnapshot, PrecipCoordinator, StationCoordinator
from custom_components.swiss_meteo.ogd import OgdError, OgdUnavailable, StationReading

from .conftest import ENTRY_ID, NOW, RUN, make_entry, make_forecast

CATALOGUE = "custom_components.swiss_meteo.coordinator.async_catalogue_latest_run"
READING = "custom_components.swiss_meteo.coordinator.async_fetch_station_reading"
PRECIP_READING = "custom_components.swiss_meteo.coordinator.async_fetch_precip_reading"
HOUR = timedelta(hours=1)
DAILY, HOURLY = len(DAILY_PARAMS), len(HOURLY_PARAMS)


def fetched(fetch) -> list[tuple[str, ...]]:
    """The parameter sets the forecast was read for, in order."""
    return [call.args[3] for call in fetch.call_args_list]


def issue(hass: HomeAssistant, key: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{key}_{ENTRY_ID}")


# --- forecast ----------------------------------------------------------------


async def test_first_read_takes_days_and_hours(hass: HomeAssistant, swiss_now, fake_forecast) -> None:
    _find, fetch = fake_forecast
    coordinator = ForecastCoordinator(hass, make_entry(hass))
    assert coordinator.point == (800100, 2)
    await coordinator.async_refresh()
    snap = coordinator.data
    assert coordinator.last_update_success
    assert snap.run == RUN
    assert set(snap.daily) == set(DAILY_PARAMS) and set(snap.hourly) == set(HOURLY_PARAMS)
    assert snap.daily_fetched == NOW and snap.hourly_fetched == NOW
    assert snap.missing == []
    assert fetched(fetch) == [DAILY_PARAMS, HOURLY_PARAMS]
    assert fetch.call_args.args[1:3] == (RUN, (800100, 2))
    # one probe for the run, then one request per file
    assert snap.requests_today == 1 + DAILY + HOURLY
    assert snap.bytes_today == 2000 * (DAILY + HOURLY)
    assert (snap.last_requests, snap.last_bytes) == (HOURLY, 2000 * HOURLY)
    assert snap.traffic_day == dt_util.start_of_local_day()


async def test_nothing_is_read_while_the_run_stays(hass: HomeAssistant, swiss_now, fake_forecast, freezer) -> None:
    find, fetch = fake_forecast
    coordinator = ForecastCoordinator(hass, make_entry(hass))
    await coordinator.async_refresh()
    fetch.reset_mock()

    freezer.move_to(NOW + timedelta(minutes=15))
    await coordinator.async_refresh()
    assert fetch.call_count == 0
    assert coordinator.data.requests_today == 2 + DAILY + HOURLY
    assert (coordinator.data.last_requests, coordinator.data.last_bytes) == (1, 0)

    # a new run an hour later: the hours are read, the days are young enough
    freezer.move_to(NOW + HOUR)
    find.return_value = RUN + HOUR
    await coordinator.async_refresh()
    assert fetched(fetch) == [HOURLY_PARAMS]
    assert coordinator.data.run == RUN + HOUR
    assert coordinator.data.daily_fetched == NOW
    assert coordinator.data.hourly_fetched == NOW + HOUR

    # three hours after the days were read a new run brings them too
    fetch.reset_mock()
    freezer.move_to(NOW + 3 * HOUR)
    find.return_value = RUN + 3 * HOUR
    await coordinator.async_refresh()
    assert fetched(fetch) == [DAILY_PARAMS, HOURLY_PARAMS]
    assert coordinator.data.daily_fetched == NOW + 3 * HOUR


async def test_days_are_read_again_after_midnight(hass: HomeAssistant, swiss_now, fake_forecast, freezer) -> None:
    _find, fetch = fake_forecast
    coordinator = ForecastCoordinator(hass, make_entry(hass))
    await coordinator.async_refresh()
    yesterday = coordinator.data.traffic_day
    fetch.reset_mock()

    # ten past midnight in Switzerland, still the same run
    freezer.move_to(datetime(2026, 11, 8, 23, 10, tzinfo=NOW.tzinfo))
    await coordinator.async_refresh()
    assert fetched(fetch) == [DAILY_PARAMS]
    snap = coordinator.data
    # the traffic of the new day starts at zero
    assert snap.traffic_day == yesterday + timedelta(days=1)
    assert snap.requests_today == 1 + DAILY
    assert snap.bytes_today == 2000 * DAILY


async def test_hours_can_be_switched_off(hass: HomeAssistant, swiss_now, fake_forecast) -> None:
    _find, fetch = fake_forecast
    coordinator = ForecastCoordinator(hass, make_entry(hass, {"hourly": False}))
    assert coordinator.hourly_enabled is False
    await coordinator.async_refresh()
    assert fetched(fetch) == [DAILY_PARAMS]
    assert coordinator.data.hourly == {} and coordinator.data.hourly_fetched is None


async def test_options_win_over_the_setup_data(hass: HomeAssistant, swiss_now, fake_forecast) -> None:
    _find, fetch = fake_forecast
    entry = make_entry(hass, {"hourly": False, "extended": False}, {"hourly": True, "extended": True})
    coordinator = ForecastCoordinator(hass, entry)
    await coordinator.async_refresh()
    assert fetched(fetch) == [DAILY_PARAMS, HOURLY_PARAMS + EXTENDED_PARAMS]
    assert "nprolohs" in coordinator.data.hourly


async def test_parameters_that_could_not_be_read_are_named(hass: HomeAssistant, swiss_now, fake_forecast) -> None:
    _find, fetch = fake_forecast

    async def gaps(_session, run, point, params):
        data = make_forecast(run, point, params[1:])
        data.missing.append(params[0])
        return data

    fetch.side_effect = gaps
    coordinator = ForecastCoordinator(hass, make_entry(hass))
    await coordinator.async_refresh()
    assert coordinator.data.missing == ["jp2000d0", "tre200h0"]
    assert "jp2000d0" not in coordinator.data.daily


async def test_run_is_found_through_the_catalogue(hass: HomeAssistant, swiss_now, fake_forecast, caplog) -> None:
    find, _fetch = fake_forecast
    find.return_value = None
    coordinator = ForecastCoordinator(hass, make_entry(hass))
    with patch(CATALOGUE, return_value=None) as catalogue:
        await coordinator.async_refresh()
        assert coordinator.last_update_success is False
        assert "MeteoSwiss has published no local forecast run for the last hours" in caplog.text

        catalogue.return_value = RUN
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert coordinator.data.run == RUN

        # no run named any more: the one at hand is shown while it is young enough
        catalogue.return_value = None
        await coordinator.async_refresh()
        assert coordinator.last_update_success and coordinator.data.run == RUN


async def test_run_check_fails(hass: HomeAssistant, swiss_now, fake_forecast, freezer) -> None:
    find, fetch = fake_forecast
    find.side_effect = OgdUnavailable("HTTP 503 for the probe")
    coordinator = ForecastCoordinator(hass, make_entry(hass))

    # nothing to show yet: a failure, and a repair notice after the third in a row
    for _attempt in range(2):
        await coordinator.async_refresh()
        assert coordinator.last_update_success is False
        assert issue(hass, "forecast_unreachable") is None
    await coordinator.async_refresh()
    notice = issue(hass, "forecast_unreachable")
    assert notice is not None
    assert notice.translation_placeholders == {"error": "HTTP 503 for the probe"}

    find.side_effect = None
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert issue(hass, "forecast_unreachable") is None

    # with a run at hand the failed check changes nothing ...
    find.side_effect = OgdUnavailable("HTTP 503 for the probe")
    fetch.reset_mock()
    freezer.move_to(RUN + timedelta(hours=12))
    await coordinator.async_refresh()
    assert coordinator.last_update_success and coordinator.data.run == RUN
    assert fetch.call_count == 0

    # ... until the run is older than twelve hours
    freezer.move_to(RUN + timedelta(hours=12, minutes=1))
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False


async def test_new_run_cannot_be_read(hass: HomeAssistant, swiss_now, fake_forecast, freezer, caplog) -> None:
    find, fetch = fake_forecast
    coordinator = ForecastCoordinator(hass, make_entry(hass))
    await coordinator.async_refresh()
    message = "not read, keeping the previous one"

    freezer.move_to(NOW + HOUR)
    find.return_value = RUN + HOUR
    fetch.side_effect = OgdUnavailable("no forecast file could be read")
    for _attempt in range(2):
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert coordinator.data.run == RUN
    # said once per run
    assert caplog.text.count(message) == 1

    freezer.move_to(NOW + 2 * HOUR)
    find.return_value = RUN + 2 * HOUR
    await coordinator.async_refresh()
    assert caplog.text.count(message) == 2

    # a file that answers but makes no sense is a failure at once
    fetch.side_effect = OgdError("unexpected file layout")
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    assert "unexpected file layout" in caplog.text

    # and so is the outage once the kept run is too old
    fetch.side_effect = OgdUnavailable("no forecast file could be read")
    freezer.move_to(RUN + timedelta(hours=13))
    find.return_value = RUN + 13 * HOUR
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    assert caplog.text.count(message) == 2


def test_age_of_a_kept_run() -> None:
    assert ForecastCoordinator._usable(ForecastSnapshot(), NOW) is False
    assert ForecastCoordinator._usable(ForecastSnapshot(run=RUN), NOW) is True
    # a run without a zone is read as UTC
    assert ForecastCoordinator._usable(ForecastSnapshot(run=RUN.replace(tzinfo=None)), NOW) is True
    assert ForecastCoordinator._usable(ForecastSnapshot(run=RUN - timedelta(hours=11)), NOW) is False


# --- station -----------------------------------------------------------------


async def test_station_reading_and_its_age(hass: HomeAssistant, swiss_now, freezer) -> None:
    coordinator = StationCoordinator(hass, make_entry(hass, {"station": "SMA"}))
    assert coordinator.station == "SMA"
    assert coordinator.fresh is False  # nothing read yet
    reading = StationReading(abbr="SMA", timestamp=NOW - timedelta(minutes=10), values={"tre200s0": 7.5})
    with patch(READING, return_value=reading) as read:
        await coordinator.async_refresh()
    assert read.call_args.args[1] == "SMA"
    assert coordinator.data is reading and coordinator.fresh

    freezer.move_to(NOW + timedelta(minutes=35))
    assert coordinator.fresh is True
    freezer.move_to(NOW + timedelta(minutes=36))
    assert coordinator.fresh is False


async def test_station_from_the_options(hass: HomeAssistant, swiss_now) -> None:
    entry = make_entry(hass, {"station": "SMA"}, {"station": "BER"})
    assert StationCoordinator(hass, entry).station == "BER"


async def test_station_repair_notice_after_an_hour_of_failures(hass: HomeAssistant, swiss_now) -> None:
    coordinator = StationCoordinator(hass, make_entry(hass, {"station": "SMA"}))
    with patch(READING, side_effect=OgdError("station file of SMA has no rows")) as read:
        for _attempt in range(5):
            await coordinator.async_refresh()
            assert coordinator.last_update_success is False
            assert issue(hass, "station_unreadable") is None
        await coordinator.async_refresh()
        notice = issue(hass, "station_unreadable")
        assert notice is not None
        assert notice.translation_placeholders == {"station": "SMA", "error": "station file of SMA has no rows"}

        read.side_effect = None
        read.return_value = StationReading(abbr="SMA", timestamp=NOW, values={})
        await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert issue(hass, "station_unreadable") is None


# --- precipitation station ---------------------------------------------------


async def test_precipitation_station_reading(hass: HomeAssistant, swiss_now, freezer) -> None:
    entry = make_entry(hass, {"station": "SMA", "precip_station": "WAG"})
    coordinator = PrecipCoordinator(hass, entry)
    assert coordinator.station == "WAG"
    assert coordinator.fresh is False  # nothing read yet
    reading = StationReading(abbr="WAG", timestamp=NOW - timedelta(minutes=10), values={"rre150z0": 1.4})
    with patch(PRECIP_READING, return_value=reading) as read, patch(READING) as weather_station:
        await coordinator.async_refresh()
    # its own file, not the weather station's
    assert read.call_args.args[1] == "WAG"
    weather_station.assert_not_called()
    assert coordinator.data is reading and coordinator.fresh

    freezer.move_to(NOW + timedelta(minutes=36))
    assert coordinator.fresh is False


async def test_precipitation_station_from_the_options(hass: HomeAssistant, swiss_now) -> None:
    entry = make_entry(hass, {"precip_station": "WAG"}, {"precip_station": "BEP"})
    assert PrecipCoordinator(hass, entry).station == "BEP"


async def test_precipitation_station_repair_notice_after_an_hour_of_failures(hass: HomeAssistant, swiss_now) -> None:
    coordinator = PrecipCoordinator(hass, make_entry(hass, {"station": "SMA", "precip_station": "WAG"}))
    with patch(PRECIP_READING, side_effect=OgdError("station file of WAG has no rows")) as read:
        for _attempt in range(5):
            await coordinator.async_refresh()
            assert coordinator.last_update_success is False
            assert issue(hass, "precip_station_unreadable") is None
        await coordinator.async_refresh()
        notice = issue(hass, "precip_station_unreadable")
        assert notice is not None
        assert notice.translation_placeholders == {"station": "WAG", "error": "station file of WAG has no rows"}
        # a notice of its own: the weather station is not blamed
        assert issue(hass, "station_unreadable") is None

        read.side_effect = None
        read.return_value = StationReading(abbr="WAG", timestamp=NOW, values={})
        await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert issue(hass, "precip_station_unreadable") is None
