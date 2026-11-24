"""The station's climate: the normal of the calendar day, the day's
records, yesterday against its normal, the first frost and snow of the
season — and how sparingly the large archive is read."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.swiss_meteo.climatology import (
    ClimateCoordinator,
    archive_url,
    assemble,
    build_table,
    climate_store,
    parse_days,
    recent_url,
    season_first,
)

from .climate_files import archive, climate_routes, recent, row
from .conftest import ENTRY_ID, NOW, make_entry
from .fakes import FakeResponse, FakeSession
from .feeds import entity, setup_everything

SESSION = "custom_components.swiss_meteo.climatology.async_get_clientsession"
TODAY = date(2026, 11, 8)


def figures(archive_body: bytes | None = None, recent_body: bytes | None = None, today: date = TODAY):
    table = build_table(parse_days(archive_body or archive()))
    return assemble(table, parse_days(recent_body or recent()), today, NOW)


def test_rows_of_a_daily_file() -> None:
    days = parse_days(recent(row("not a date", 1.0), "broken"))
    assert days[date(2026, 11, 7)] == {"tre200d0": 8.0, "tre200dx": 11.0, "tre200dn": 4.0, "rka150d0": 2.5, "sre000d0": 120.0, "htoautd0": 0.0}
    assert days[TODAY]["tre200d0"] is None
    assert len(days) == 5


def test_normal_of_the_day_from_the_reference_period() -> None:
    climate = figures()
    # fifteen days by thirty years, mean 5.0 with highs and lows 4 away
    assert (climate.normal_mean, climate.normal_high, climate.normal_low) == (5.0, 9.0, 1.0)
    assert climate.normal_years == 30 and climate.day == TODAY
    assert climate.first_year == 1921


def test_no_normal_from_fewer_than_ten_years() -> None:
    climate = figures(archive(2012, 2020))
    assert (climate.normal_mean, climate.normal_high, climate.normal_low, climate.normal_years) == (None, None, None, 9)
    assert climate.record_high == 21.0  # the records need no reference period
    assert figures(archive(2011, 2020)).normal_years == 10
    # years outside 1991-2020 do not count
    assert figures(archive(2015, 2025)).normal_mean is None


def test_records_of_the_calendar_day() -> None:
    climate = figures()
    assert (climate.record_high, climate.record_high_year) == (21.0, 1921)
    assert (climate.record_low, climate.record_low_year) == (-9.0, 1956)
    # the current year can set a record as well
    hot = figures(recent_body=recent(row("08.11.2026", 15.0, 23.5, 9.0)))
    assert (hot.record_high, hot.record_high_year) == (23.5, 2026)
    assert (hot.record_low, hot.record_low_year) == (-9.0, 1956)
    # a day the station never measured has none
    assert (figures(today=date(2026, 6, 1)).record_high, figures(today=date(2026, 6, 1)).normal_mean) == (None, None)


def test_yesterday_against_its_normal() -> None:
    climate = figures()
    assert climate.yesterday == date(2026, 11, 7)
    assert climate.yesterday_values["tre200d0"] == 8.0
    assert climate.anomaly == 3.0
    # nothing measured yet this year
    empty = figures(recent_body=recent().split(b"\n")[0] + b"\n")
    assert empty.yesterday is None and empty.anomaly is None and empty.yesterday_values == {}


def test_first_frost_and_first_snow_of_the_season() -> None:
    climate = figures()
    assert climate.first_frost == date(2026, 10, 28)
    assert climate.first_snow == date(2026, 11, 3)
    # before July the season is the one that began last year
    spring = figures(today=date(2026, 5, 2))
    assert spring.first_frost is None and spring.first_snow is None
    days = parse_days(recent())
    assert season_first(days, 2026, "tre200dn", lambda v: v < 0) == date(2026, 10, 28)
    assert season_first(days, 2025, "tre200dn", lambda v: v < 0) is None


def test_season_that_began_in_the_archive() -> None:
    # the archive ends in December: its autumn belongs to the running season
    old = archive(1991, 2020, row("20.10.2025", 1.0, 5.0, -1.5, 0, 0, 0), row("30.11.2025", -1.0, 0.0, -3.0, 5.0, 12, 0), row("31.12.2025", 0.0, 1.0, -1.0))
    table = build_table(parse_days(old))
    assert (table["season"], table["frost"], table["snow"], table["through"]) == (2025, "2025-10-20", "2025-11-30", "2025-12-31")
    this_year = recent(row("10.01.2026", -4.0, -1.0, -8.0, 0, 20, 100))
    winter = assemble(table, parse_days(this_year), date(2026, 2, 1), NOW)
    assert winter.first_frost == date(2025, 10, 20) and winter.first_snow == date(2025, 11, 30)
    # the next season starts from nothing
    autumn = assemble(table, parse_days(this_year), TODAY, NOW)
    assert autumn.first_frost == date(2026, 10, 28)


def test_29_february_is_a_day_like_any_other() -> None:
    leap = archive(1991, 2020, row("29.02.2000", 4.0, 9.0, -2.0), row("28.02.2001", 3.0, 8.0, -3.0))
    table = build_table(parse_days(leap))
    assert table["days"]["02-29"][4:] == [9.0, 2000, -2.0, 2000]
    assert table["days"]["02-28"][4:] == [8.0, 2001, -3.0, 2001]
    assert len(table["days"]) == 366


# --- reading -------------------------------------------------------------------


async def test_archive_is_read_once_and_remembered(hass: HomeAssistant, swiss_now, freezer, hass_storage) -> None:
    session = FakeSession(climate_routes())
    traffic: list[tuple[int, int]] = []
    entry = make_entry(hass, {"station": "SMA"})
    with patch(SESSION, return_value=session):
        coordinator = ClimateCoordinator(hass, entry, lambda requests, nbytes: traffic.append((requests, nbytes)))
        await coordinator.async_refresh()
        assert coordinator.last_update_success and coordinator.data.normal_mean == 5.0
        assert session.urls("GET") == [archive_url("SMA"), recent_url("SMA")]
        assert sum(nbytes for _n, nbytes in traffic) == len(archive()) + len(recent())

        # three hours later only the current year is read
        freezer.tick(timedelta(hours=3))
        await coordinator.async_refresh()
        assert session.urls("GET")[2:] == [recent_url("SMA")]
        assert len(session.urls("HEAD")) == 1  # the one before the first read

        # after a restart the table comes from the storage
        freezer.tick(timedelta(minutes=2))
        await hass.async_block_till_done()
        stored = hass_storage[f"swiss_meteo.climate_{ENTRY_ID}"]["data"]
        assert stored["station"] == "SMA" and len(stored["days"]) == 366
        again = ClimateCoordinator(hass, entry)
        await again.async_refresh()
        assert again.data.record_high == 21.0
        assert session.urls("GET")[3:] == [recent_url("SMA")]


async def test_archive_is_looked_at_again_after_a_month(hass: HomeAssistant, swiss_now, freezer) -> None:
    stamps = {"value": "Wed, 18 Feb 2026 21:04:28 GMT"}
    bodies = {"archive": archive()}

    def served(method: str, _url: str, _headers: dict) -> FakeResponse:
        if method == "HEAD":
            return FakeResponse(200, headers={"Last-Modified": stamps["value"]})
        return FakeResponse(200, bodies["archive"], {"Content-Length": str(len(bodies["archive"]))})

    session = FakeSession({archive_url("SMA"): served, recent_url("SMA"): recent()})
    with patch(SESSION, return_value=session):
        coordinator = ClimateCoordinator(hass, make_entry(hass, {"station": "SMA"}))
        await coordinator.async_refresh()
        freezer.tick(timedelta(days=31))
        await coordinator.async_refresh()
        # unchanged: asked, not read
        assert session.urls("GET").count(archive_url("SMA")) == 1 and len(session.urls("HEAD")) == 2
        # a new archive (a year was added): read again
        freezer.tick(timedelta(days=31))
        stamps["value"] = "Thu, 18 Feb 2027 21:00:00 GMT"
        bodies["archive"] = archive(1991, 2020, row("09.01.1900", 9.0, 25.0, 3.0))  # by then it is 9 January
        await coordinator.async_refresh()
        assert session.urls("GET").count(archive_url("SMA")) == 2
        assert (coordinator.data.record_high, coordinator.data.record_high_year) == (25.0, 1900)


async def test_outage_keeps_the_figures_for_two_days(hass: HomeAssistant, swiss_now, freezer, caplog) -> None:
    session = FakeSession(climate_routes())
    with patch(SESSION, return_value=session):
        coordinator = ClimateCoordinator(hass, make_entry(hass, {"station": "SMA"}))
        await coordinator.async_refresh()
        session.routes[recent_url("SMA")] = FakeResponse(503)
        freezer.tick(timedelta(hours=3))
        await coordinator.async_refresh()
        assert coordinator.last_update_success and coordinator.data.normal_mean == 5.0
        assert caplog.text.count("keeping the last figures") == 1
        freezer.tick(timedelta(hours=3))
        await coordinator.async_refresh()
        assert caplog.text.count("keeping the last figures") == 1  # said once
        freezer.tick(timedelta(days=2))
        await coordinator.async_refresh()
        assert coordinator.last_update_success is False


async def test_station_without_an_archive(hass: HomeAssistant, swiss_now) -> None:
    with patch(SESSION, return_value=FakeSession({archive_url("SMA"): b"station_abbr;reference_timestamp;tre200d0\n", recent_url("SMA"): recent()})):
        coordinator = ClimateCoordinator(hass, make_entry(hass, {"station": "SMA"}))
        await coordinator.async_refresh()
    assert coordinator.last_update_success is False and coordinator.data is None


# --- sensors -------------------------------------------------------------------


def state(hass: HomeAssistant, key: str) -> str:
    return hass.states.get(entity("sensor", key)).state


def attributes(hass: HomeAssistant, key: str) -> dict:
    return dict(hass.states.get(entity("sensor", key)).attributes)


async def test_climate_sensors(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_everything(hass, setup_integration)
    assert state(hass, "normal_temperature") == "5.0"
    normal = attributes(hass, "normal_temperature")
    assert (normal["normal_high"], normal["normal_low"], normal["period"], normal["years"]) == (9.0, 1.0, "1991-2020", 30)
    assert state(hass, "yesterday_temperature") == "8.0"
    yesterday = attributes(hass, "yesterday_temperature")
    assert (yesterday["date"], yesterday["high"], yesterday["low"], yesterday["precipitation"], yesterday["sunshine_hours"]) == ("2026-11-07", 11.0, 4.0, 2.5, 2.0)
    assert state(hass, "temperature_anomaly") == "3.0"
    assert state(hass, "record_high") == "21.0" and attributes(hass, "record_high")["year"] == 1921
    assert state(hass, "record_low") == "-9.0" and attributes(hass, "record_low")["since"] == 1921
    assert state(hass, "first_frost") == "2026-10-28"
    assert state(hass, "first_snow") == "2026-11-03"
    assert attributes(hass, "first_snow")["season_from"] == "2026-07-01"
    # what was read is part of the entry's traffic
    assert entry.runtime_data.climate.last_update_success


async def test_no_climate_sensors_without_a_station(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_integration()
    assert entry.runtime_data.climate is None
    assert hass.states.get(entity("sensor", "normal_temperature")) is None


async def test_the_new_day_asks_for_its_own_figures(hass: HomeAssistant, setup_integration, freezer) -> None:
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    entry = await setup_everything(hass, setup_integration)
    climate = entry.runtime_data.climate
    assert climate.data.day == TODAY
    midnight = NOW.replace(hour=23, minute=1, second=0)  # 00:01 local time
    freezer.move_to(midnight)
    async_fire_time_changed(hass, midnight)
    await hass.async_block_till_done(wait_background_tasks=True)
    freezer.tick(timedelta(seconds=30))  # the refresh request waits a moment for others
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert climate.data.day == date(2026, 11, 9)


async def test_removing_the_entry_removes_the_table(hass: HomeAssistant, setup_integration, hass_storage, freezer) -> None:
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    entry = await setup_everything(hass, setup_integration)
    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    key = f"swiss_meteo.climate_{ENTRY_ID}"
    assert key in hass_storage
    assert climate_store(hass, ENTRY_ID).key == key
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


# --- climate stripes and the running month ---------------------------------------


def full_years(means: dict[int, float], rain: float | None = None) -> dict:
    """Every day of the given years with the year's mean (and a daily rain)."""
    days = {}
    for year, mean in means.items():
        day = date(year, 1, 1)
        while day.year == year:
            days[day] = {"tre200d0": mean, "tre200dx": mean + 4, "tre200dn": mean - 4, "rka150d0": rain, "sre000d0": None, "htoautd0": None}
            day += timedelta(days=1)
    return days


def test_yearly_means_for_the_stripes() -> None:
    days = full_years({1960: 8.0, 1961: 8.5, 2000: 9.25})
    # a year with too few measured days does not count
    for n in range(40):
        days[date(1962, 1, 1) + timedelta(days=n)] = {"tre200d0": 1.0, "tre200dx": 2.0, "tre200dn": 0.0, "rka150d0": None, "sre000d0": None, "htoautd0": None}
    assert build_table(days)["years"] == {"1960": 8.0, "1961": 8.5, "2000": 9.25}
    assert build_table(parse_days(archive()))["years"] == {}


def test_normal_precipitation_of_a_month() -> None:
    table = build_table(full_years({year: 9.0 for year in range(1991, 2021)}, rain=1.0))
    assert table["months"]["11"] == [30.0, 30] and table["months"]["02"][1] == 30
    assert 28.0 < table["months"]["02"][0] < 28.5  # leap years in the mean
    # too few years, or months measured on too few days: no normal
    assert build_table(full_years({year: 9.0 for year in range(2012, 2021)}, rain=1.0))["months"]["11"] == [None, 9]
    assert build_table(parse_days(archive()))["months"]["11"] == [None, 0]


def test_running_month_against_its_normal() -> None:
    climate = figures()
    # 3 and 7 November are measured: 0.5 and 8.0 °C, 6.0 and 2.5 mm
    assert climate.month_days == 2
    assert (climate.month_mean, climate.month_normal) == (4.2, 5.0)
    assert (climate.month_precipitation, climate.month_precipitation_normal) == (8.5, None)
    # on the first of a month nothing is measured yet
    first = figures(today=date(2026, 12, 1))
    assert (first.month_days, first.month_mean, first.month_normal, first.month_precipitation) == (0, None, None, None)
    with_rain = assemble(build_table(full_years({year: 9.0 for year in range(1991, 2021)}, rain=1.0)), parse_days(recent()), TODAY, NOW)
    assert with_rain.month_precipitation_normal == 30.0 and with_rain.month_normal == 9.0


async def test_month_sensors(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    assert state(hass, "month_temperature") == "4.2"
    month = attributes(hass, "month_temperature")
    assert (month["days"], month["normal_of_these_days"], month["anomaly"], month["month"]) == (2, 5.0, -0.8, "2026-11")
    assert state(hass, "month_precipitation") == "8.5"
    rain = attributes(hass, "month_precipitation")
    assert (rain["normal_of_the_month"], rain["percent_of_normal"]) == (None, None)


async def test_stripes_for_the_card(hass: HomeAssistant, setup_integration, hass_ws_client) -> None:
    entry = await setup_everything(hass, setup_integration)
    client = await hass_ws_client(hass)

    async def ask(entity_id: str) -> dict:
        await client.send_json_auto_id({"type": "swiss_meteo/climate", "entity_id": entity_id})
        return await client.receive_json()

    # the invented archive has no complete year
    answer = await ask(entity("weather"))
    assert answer["success"] is False and answer["error"]["code"] == "not_found"

    climate = entry.runtime_data.climate
    climate._table["years"] = {str(year): 8.0 for year in range(1961, 1991)} | {"2024": 10.5}
    answer = await ask(entity("sensor", "normal_temperature"))
    assert answer["success"] is True
    stripes = answer["result"]
    assert stripes["reference"] == 8.0 and stripes["reference_period"] == [1961, 1990]
    assert stripes["years"][0] == {"year": 1961, "mean": 8.0} and stripes["years"][-1] == {"year": 2024, "mean": 10.5}

    # a young station is coloured against the mean of all its years
    climate._table["years"] = {"2015": 9.0, "2016": 10.0, "2017": 11.0}
    stripes = (await ask(entity("weather")))["result"]
    assert stripes["reference"] == 10.0 and stripes["reference_period"] == [2015, 2017]

    hass.states.async_set("sensor.something_else", "1")
    assert (await ask("sensor.something_else"))["success"] is False


async def test_a_table_of_the_previous_version_is_built_anew(hass: HomeAssistant, swiss_now, hass_storage) -> None:
    hass_storage[f"swiss_meteo.climate_{ENTRY_ID}"] = {"version": 1, "minor_version": 1, "key": f"swiss_meteo.climate_{ENTRY_ID}", "data": {"station": "SMA", "days": {}, "checked": NOW.isoformat()}}
    session = FakeSession(climate_routes())
    with patch(SESSION, return_value=session):
        coordinator = ClimateCoordinator(hass, make_entry(hass, {"station": "SMA"}))
        await coordinator.async_refresh()
    assert archive_url("SMA") in session.urls("GET")
    assert coordinator.data.normal_mean == 5.0


# --- review of 1.9.0 -------------------------------------------------------------


def test_columns_a_station_does_not_have() -> None:
    days = parse_days(b"station_abbr;reference_timestamp;tre200d0\nSMA;07.11.2026 00:00;8.0\nSMA;08.11.2026 00:00\n")
    assert days[date(2026, 11, 7)] == {"tre200d0": 8.0, "tre200dx": None, "tre200dn": None, "rka150d0": None, "sre000d0": None, "htoautd0": None}
    assert days[date(2026, 11, 8)]["tre200d0"] is None
    assert parse_days(b"") == {} and parse_days(b"something;else\n1;2\n") == {}


def test_an_old_day_is_not_yesterday() -> None:
    assert figures(today=date(2026, 11, 9)).yesterday == date(2026, 11, 7)  # not published yet
    stopped = figures(today=date(2026, 11, 10))
    assert stopped.yesterday is None and stopped.anomaly is None and stopped.yesterday_values == {}


async def test_first_days_survive_the_new_year(hass: HomeAssistant, swiss_now, freezer) -> None:
    routes = climate_routes()
    session = FakeSession(routes)
    with patch(SESSION, return_value=session):
        coordinator = ClimateCoordinator(hass, make_entry(hass, {"station": "SMA"}))
        await coordinator.async_refresh()
        assert coordinator.data.first_frost == date(2026, 10, 28)
        # in January the current file starts anew and the archive still ends before the autumn
        freezer.move_to(datetime(2027, 1, 10, 12, 0, tzinfo=UTC))
        session.routes[recent_url("SMA")] = recent(row("09.01.2027", -3.0, 0.0, -6.0, 0, 15, 0)).replace(b".2026 ", b".2025 ")
        await coordinator.async_refresh()
        assert coordinator.data.first_frost == date(2026, 10, 28) and coordinator.data.first_snow == date(2026, 11, 3)
        # the next season forgets them
        freezer.move_to(datetime(2027, 8, 1, 12, 0, tzinfo=UTC))
        await coordinator.async_refresh()
        assert coordinator.data.first_frost is None and coordinator.data.first_snow is None


async def test_archive_that_is_behind_is_looked_at_daily(hass: HomeAssistant, swiss_now, freezer) -> None:
    session = FakeSession(climate_routes())  # the archive ends in 2020
    with patch(SESSION, return_value=session):
        coordinator = ClimateCoordinator(hass, make_entry(hass, {"station": "SMA"}))
        await coordinator.async_refresh()
        freezer.tick(timedelta(hours=23))
        await coordinator.async_refresh()
        assert len(session.urls("HEAD")) == 1
        freezer.tick(timedelta(hours=2))
        await coordinator.async_refresh()
        assert len(session.urls("HEAD")) == 2


async def test_renewed_archive_that_cannot_be_read_keeps_the_table(hass: HomeAssistant, swiss_now, freezer) -> None:
    stamp = {"value": "old"}

    def served(method: str, _url: str, _headers: dict) -> FakeResponse:
        if method == "HEAD":
            return FakeResponse(200, headers={"Last-Modified": stamp["value"]})
        return FakeResponse(200, archive()) if stamp["value"] == "old" else FakeResponse(503)

    session = FakeSession({archive_url("SMA"): served, recent_url("SMA"): recent()})
    with patch(SESSION, return_value=session):
        coordinator = ClimateCoordinator(hass, make_entry(hass, {"station": "SMA"}))
        await coordinator.async_refresh()
        stamp["value"] = "new"
        freezer.tick(timedelta(days=31))
        await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert coordinator.data.day == date(2026, 12, 9)
