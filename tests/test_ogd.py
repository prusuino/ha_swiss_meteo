"""Unit tests of the MeteoSwiss open-data readers: CSV and row parsing,
distances, nearest-neighbour ranking and the file URLs."""
from __future__ import annotations

from datetime import UTC, datetime

from custom_components.swiss_meteo.ogd import (
    Point,
    Station,
    _float,
    _key,
    _parse_csv,
    _parse_rows,
    _parse_station_timestamp,
    distance_km,
    forecast_file_url,
    nearest,
    station_now_url,
)


def test_float_handles_blank_and_garbage() -> None:
    assert _float("12.5") == 12.5
    assert _float("") is None
    assert _float(None) is None
    assert _float("n/a") is None


def test_parse_csv_is_semicolon_separated_latin1() -> None:
    body = "station_abbr;name;height\nBER;Bern / Zollikofen;553\nGVE;Genève;412\n".encode("latin-1")
    rows = _parse_csv(body)
    assert [r["station_abbr"] for r in rows] == ["BER", "GVE"]
    assert rows[1]["name"] == "Genève"


def test_distance_bern_zurich_about_95_km() -> None:
    bern = (46.948, 7.447)
    zurich = (47.377, 8.540)
    assert 93 <= distance_km(*bern, *zurich) <= 97
    assert distance_km(*bern, *bern) == 0


def test_nearest_ranks_by_distance_and_limits_count() -> None:
    stations = [
        Station("BER", "Bern / Zollikofen", "BE", 553, 46.991, 7.464),
        Station("SMA", "Zürich / Fluntern", "ZH", 556, 47.378, 8.566),
        Station("GVE", "Genève / Cointrin", "GE", 412, 46.248, 6.128),
    ]
    ranked = nearest(stations, 47.0, 7.5, count=2)
    assert [s.abbr for _d, s in ranked] == ["BER", "SMA"]
    assert ranked[0][0] < ranked[1][0]


def test_point_key_is_id_then_type() -> None:
    point = Point(point_type=2, point_id=800100, name="Zürich", postal_code="8001", station_abbr="SMA", height=408.0, lat=47.37, lon=8.54)
    assert point.key == (800100, 2)


def test_station_now_url_uses_lower_case_abbreviation() -> None:
    url = station_now_url("BER")
    assert url.endswith("/ber/ogd-smn_ber_t_now.csv")


def test_parse_station_timestamp_is_utc() -> None:
    ts = _parse_station_timestamp(" 07.11.2026 16:50 ")
    assert ts == datetime(2026, 11, 7, 16, 50, tzinfo=UTC)


def test_forecast_file_url_has_day_folder_and_run_stamp() -> None:
    run = datetime(2026, 11, 8, 6, 0, tzinfo=UTC)
    url = forecast_file_url(run, "tre200h0")
    assert "/20261108-ch/" in url
    assert url.endswith("vnut12.lssw.202611080600.tre200h0.csv")


def test_key_reads_point_type_and_timestamp_and_skips_header() -> None:
    assert _key(b"800100;2;202611080600;12.3") == (800100, 2, "202611080600")
    assert _key(b"point_id;point_type;timestamp;value") is None
    assert _key(b"too;short") is None


def test_parse_rows_sorts_by_time_and_keeps_missing_values() -> None:
    rows = [
        b"800100;2;202611080800;",
        b"800100;2;202611080600;12.3",
        b"800100;2;202611080700;11.9",
        b"broken line",
    ]
    series = _parse_rows(rows)
    assert [ts.hour for ts, _v in series] == [6, 7, 8]
    assert [v for _ts, v in series] == [12.3, 11.9, None]
    assert all(ts.tzinfo is UTC for ts, _v in series)
