"""Figures derived from the forecast series: daily means and heating
degree days, radiation and sunshine sums, the coming rain, the night
minimum. Used by the sensors and the binary sensors."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.util import dt as dt_util

from .coordinator import ForecastSnapshot, Series
from .forecast import daily_values, day_from_hourly, hour_floor

# Heating degree days after SIA 381/3 (the Swiss standard): a day counts
# when its mean is below 12 °C, and contributes 20 °C minus the mean.
HDD_THRESHOLD = 12.0
HDD_BASE = 20.0

RAIN_THRESHOLD_MM = 0.1
# "Tonight" ends at this local hour of the next morning.
NIGHT_END_HOUR = 9


def day_mean(snap: ForecastSnapshot, day: date) -> float | None:
    """The day's mean temperature: the mean of the hourly values when
    the day is covered (at least 20 hours), else the mean of the daily
    high and low."""
    temps = snap.hourly.get("tre200h0")
    if temps:
        values = [v for ts, v in temps if v is not None and dt_util.as_local(ts).date() == day]
        if len(values) >= 20:
            return round(sum(values) / len(values), 1)
    high = daily_values(snap, "tre200px").get(day)
    low = daily_values(snap, "tre200pn").get(day)
    if high is None or low is None:
        return None
    return round((high + low) / 2, 1)


def heating_degree_days(mean: float | None) -> float | None:
    if mean is None:
        return None
    return round(HDD_BASE - mean, 1) if mean < HDD_THRESHOLD else 0.0


def day_sum(snap: ForecastSnapshot, param: str, day: date) -> float | None:
    """Sum of an hourly parameter over a local day (hours in the run only)."""
    return day_from_hourly(snap.hourly.get(param), day, sum)


def hours_covered(snap: ForecastSnapshot, day: date) -> int:
    temps = snap.hourly.get("tre200h0") or []
    return sum(1 for ts, v in temps if v is not None and dt_util.as_local(ts).date() == day)


def window_sum(series: Series | None, hours: int) -> float | None:
    """Sum over the coming `hours` hours from the current hour on."""
    if not series:
        return None
    start = hour_floor(dt_util.utcnow())
    end = start + timedelta(hours=hours)
    values = [v for ts, v in series if v is not None and start <= ts < end]
    return round(sum(values), 1) if values else None


def next_rain(snap: ForecastSnapshot, threshold: float = RAIN_THRESHOLD_MM) -> tuple[datetime, float] | None:
    """The first coming hour with precipitation at or above the threshold:
    (hour start, amount)."""
    series = snap.hourly.get("rre150h0")
    if not series:
        return None
    start = hour_floor(dt_util.utcnow())
    for ts, v in series:
        if ts >= start and v is not None and v >= threshold:
            return ts, v
    return None


def night_minimum(snap: ForecastSnapshot) -> tuple[datetime, float] | None:
    """The lowest hourly temperature between now and 09:00 local of the
    next morning (or of today, before 09:00): (hour, temperature)."""
    temps = snap.hourly.get("tre200h0")
    if not temps:
        return None
    now = dt_util.now()
    end = now.replace(hour=NIGHT_END_HOUR, minute=0, second=0, microsecond=0)
    if now.hour >= NIGHT_END_HOUR:
        end += timedelta(days=1)
    start = hour_floor(dt_util.utcnow())
    best: tuple[datetime, float] | None = None
    for ts, v in temps:
        if v is None or ts < start or dt_util.as_local(ts) > end:
            continue
        if best is None or v < best[1]:
            best = (ts, v)
    return best
