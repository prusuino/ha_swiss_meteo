"""Turning the parameter series of a run into what the weather entity and
the sensors show: the value in force now, the daily and the hourly
forecast lists."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.util import dt as dt_util

from .coordinator import ForecastSnapshot, Series


def value_at(series: Series | None, when: datetime) -> float | None:
    """The value whose timestamp is the latest at or before `when`; the
    first value when `when` precedes the series (a run starts an hour or
    two before now)."""
    if not series:
        return None
    chosen: float | None = None
    for ts, value in series:
        if ts <= when:
            chosen = value
        else:
            if chosen is None:
                return value
            break
    return chosen


def hour_floor(when: datetime) -> datetime:
    return when.replace(minute=0, second=0, microsecond=0)


def local_date(ts: datetime) -> date:
    """The daily files stamp a day as midnight UTC of that calendar day;
    the day they mean is the local calendar day of the same date."""
    return ts.date()


def daily_values(snap: ForecastSnapshot, param: str) -> dict[date, float | None]:
    return {local_date(ts): v for ts, v in snap.daily.get(param, [])}


def day_from_hourly(series: Series | None, day: date, reducer) -> float | None:
    """A daily figure reduced from the hourly values of a local day."""
    if not series:
        return None
    values = [v for ts, v in series if v is not None and dt_util.as_local(ts).date() == day]
    return reducer(values) if values else None


def daily_forecast(snap: ForecastSnapshot) -> list[dict]:
    """One entry per forecast day, in the shape the weather entity emits."""
    from .symbols import condition_for  # local import keeps symbols optional for tests

    symbols = daily_values(snap, "jp2000d0")
    highs = daily_values(snap, "tre200px")
    lows = daily_values(snap, "tre200pn")
    precip = daily_values(snap, "rka150p0")
    p10 = daily_values(snap, "rreq10p0")
    p90 = daily_values(snap, "rreq90p0")
    prob = snap.hourly.get("rp0003i0")
    wind = snap.hourly.get("fu3010h0")
    gust = snap.hourly.get("fu3010h1")
    sunshine = snap.hourly.get("sre000h0")
    today = dt_util.now().date()
    out: list[dict] = []
    for day in sorted(set(symbols) | set(highs) | set(lows)):
        if day < today:
            continue
        start = dt_util.start_of_local_day(datetime.combine(day, datetime.min.time()))
        entry = {
            "datetime": start.isoformat(),
            "condition": condition_for(symbols.get(day), daytime=True),
            "native_temperature": highs.get(day),
            "native_templow": lows.get(day),
            "native_precipitation": precip.get(day),
            "precipitation_probability": day_from_hourly(prob, day, max),
            "native_wind_speed": day_from_hourly(wind, day, max),
            "native_wind_gust_speed": day_from_hourly(gust, day, max),
            "symbol": _int(symbols.get(day)),
            "precipitation_min": p10.get(day),
            "precipitation_max": p90.get(day),
            "sunshine_hours": _hours(day_from_hourly(sunshine, day, sum)),
        }
        out.append({k: v for k, v in entry.items() if v is not None or k in ("datetime", "condition")})
    return out


def _hours(minutes: float | None) -> float | None:
    """Sunshine minutes summed over a day, as hours with one decimal."""
    return round(minutes / 60, 1) if minutes is not None else None


def cloud_coverage(snap: ForecastSnapshot, when: datetime) -> float | None:
    """Total cover from the three layers (the share of sky any layer covers)."""
    layers = [value_at(snap.hourly.get(p), when) for p in ("nprolohs", "npromths", "nprohihs")]
    if any(v is None for v in layers):
        return None
    clear = 1.0
    for v in layers:
        clear *= 1 - min(max(v, 0.0), 1.0)
    return round((1 - clear) * 100)


def hourly_forecast(snap: ForecastSnapshot, hours: int = 216) -> list[dict]:
    """One entry per hour from the current hour on."""
    from .symbols import condition_for

    temps = snap.hourly.get("tre200h0")
    if not temps:
        return []
    now_hour = hour_floor(dt_util.utcnow())
    out: list[dict] = []
    for ts, temp in temps:
        if ts < now_hour or len(out) >= hours:
            continue
        local = dt_util.as_local(ts)
        symbol = value_at(snap.hourly.get("jww003i0"), ts)
        entry = {
            "datetime": local.isoformat(),
            "condition": condition_for(symbol, daytime=None),
            "native_temperature": temp,
            "native_precipitation": value_at(snap.hourly.get("rre150h0"), ts),
            "precipitation_probability": _int(value_at(snap.hourly.get("rp0003i0"), ts)),
            "native_wind_speed": value_at(snap.hourly.get("fu3010h0"), ts),
            "native_wind_gust_speed": value_at(snap.hourly.get("fu3010h1"), ts),
            "wind_bearing": value_at(snap.hourly.get("dkl010h0"), ts),
            "cloud_coverage": cloud_coverage(snap, ts),
            "symbol": _int(symbol),
            "global_radiation": value_at(snap.hourly.get("gre000h0"), ts),
            "sunshine_minutes": value_at(snap.hourly.get("sre000h0"), ts),
            "temperature_min": value_at(snap.hourly.get("treq10h0"), ts),
            "temperature_max": value_at(snap.hourly.get("treq90h0"), ts),
            "precipitation_min": value_at(snap.hourly.get("rreq10h0"), ts),
            "precipitation_max": value_at(snap.hourly.get("rreq90h0"), ts),
            "zero_degree_level": value_at(snap.hourly.get("zprfr0hs"), ts),
        }
        out.append({k: v for k, v in entry.items() if v is not None or k in ("datetime", "condition")})
    return out


def next_hours(snap: ForecastSnapshot, hours: int) -> list[tuple[datetime, float | None]]:
    """(timestamp, precipitation) of the coming hours, for the rain sensors."""
    series = snap.hourly.get("rre150h0") or []
    now_hour = hour_floor(dt_util.utcnow())
    return [(ts, v) for ts, v in series if now_hour <= ts < now_hour + timedelta(hours=hours)]


def _int(value: float | None) -> int | None:
    return int(value) if value is not None else None
