"""The two daily files of a station the climate figures are read from,
invented: an archive with the first half of November for every year of the
reference period and two record days long before it, and the current year
with yesterday, a first frost and a first day with snow on the ground."""
from __future__ import annotations

from custom_components.swiss_meteo.climatology import archive_url, recent_url

HEADER = "station_abbr;reference_timestamp;tre200d0;tre200dx;tre200dn;rka150d0;htoautd0;sre000d0"


def row(day: str, mean: float | str = "", high: float | str = "", low: float | str = "", rain: float | str = "", snow: float | str = "", sun: float | str = "") -> str:
    return f"SMA;{day} 00:00;{mean};{high};{low};{rain};{snow};{sun}"


def archive(first: int = 1991, last: int = 2020, *extra: str) -> bytes:
    """1 to 15 November of every year; the mean of all years is 5.0, with
    highs 4 above and lows 4 below."""
    rows = [HEADER, row("08.11.1921", 12.0, 21.0, 6.0), row("08.11.1956", -5.0, -1.0, -9.0)]
    for year in range(first, last + 1):
        mean = round(5.0 + (year - 2005.5) * 0.1, 2)
        rows += [row(f"{day:02d}.11.{year}", mean, mean + 4, mean - 4, 1.0, 0, 60) for day in range(1, 16)]
    return "\n".join([*rows, *extra, ""]).encode("latin-1")


def recent(*extra: str) -> bytes:
    rows = [
        HEADER,
        row("27.10.2026", 3.0, 8.0, 0.4, 0, 0, 300),
        row("28.10.2026", 2.0, 7.0, -0.5, 0, 0, 300),  # the first frost
        row("03.11.2026", 0.5, 2.0, -2.0, 6.0, 3, 0),  # the first snow on the ground
        row("07.11.2026", 8.0, 11.0, 4.0, 2.5, 0, 120),  # yesterday
        row("08.11.2026"),  # today's row exists before it has values
    ]
    return "\n".join([*rows, *extra, ""]).encode("latin-1")


def climate_routes(station: str = "SMA", archive_body: bytes | None = None, recent_body: bytes | None = None) -> dict[str, bytes]:
    return {archive_url(station): archive_body or archive(), recent_url(station): recent_body or recent()}
