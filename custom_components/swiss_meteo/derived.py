"""Figures derived from the forecast series: daily means and heating
degree days, radiation and sunshine sums, the coming rain, the night
minimum, and the everyday questions (laundry, windscreen, airing at
night, watering). From the station: the feels-like temperature and the
pressure trend. Used by the sensors and the binary sensors."""
from __future__ import annotations

import math
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


WIND_WINDOW_HOURS = 6


def max_gust(snap: ForecastSnapshot, hours: int = WIND_WINDOW_HOURS) -> tuple[datetime, float] | None:
    """The strongest hourly gust peak (km/h) within the coming `hours` hours:
    (hour start, km/h)."""
    series = snap.hourly.get("fu3010h1")
    if not series:
        return None
    start = hour_floor(dt_util.utcnow())
    end = start + timedelta(hours=hours)
    best: tuple[datetime, float] | None = None
    for ts, v in series:
        if v is not None and start <= ts < end and (best is None or v > best[1]):
            best = (ts, v)
    return best


def best_window(snap: ForecastSnapshot, hours: int, within: int, criterion: str) -> dict | None:
    """The best `hours`-hour window starting within the coming `within`
    hours: least precipitation (dry), most sunshine (sunny) or lowest gusts
    (calm); ties go to the earlier window. None when the run does not cover
    a full window."""
    rain = dict(snap.hourly.get("rre150h0") or [])
    sun = dict(snap.hourly.get("sre000h0") or [])
    gust = dict(snap.hourly.get("fu3010h1") or [])
    temp = dict(snap.hourly.get("tre200h0") or [])
    first = hour_floor(dt_util.utcnow())
    best: tuple[float, dict] | None = None
    for offset in range(max(1, within)):
        start = first + timedelta(hours=offset)
        hours_in = [start + timedelta(hours=h) for h in range(hours)]
        if any(h not in rain for h in hours_in):
            continue
        p = sum(rain.get(h) or 0.0 for h in hours_in)
        sh = sum(sun.get(h) or 0.0 for h in hours_in) / 60.0
        g = max((gust.get(h) or 0.0) for h in hours_in)
        temps = [temp[h] for h in hours_in if temp.get(h) is not None]
        if criterion == "sunny":
            score = -sh + p * 0.01
        elif criterion == "calm":
            score = g + p * 0.01
        else:
            score = p + g * 0.001
        if best is None or score < best[0]:
            best = (score, {
                "found": True,
                "start": start.isoformat(),
                "end": (start + timedelta(hours=hours)).isoformat(),
                "precipitation_mm": round(p, 1),
                "sunshine_h": round(sh, 1),
                "max_gust_kmh": round(g),
                "mean_temperature": round(sum(temps) / len(temps), 1) if temps else None,
                "criterion": criterion,
            })
    return best[1] if best else None


# --- everyday questions --------------------------------------------------------

# Laundry dries outside: this many dry hours in a row between 08:00 and 20:00.
DRYING_HOURS = 4
DRYING_MAX_PROBABILITY = 30  # % chance of rain in an hour of the window
DRYING_MIN_TEMPERATURE = 5.0
# A windscreen cools below the air temperature under a clear sky: ice is
# likely from an air temperature of 1 °C between 04:00 and 08:00.
WINDSCREEN_THRESHOLD = 1.0
WINDSCREEN_HOURS = (4, 8)
# Airing at night pays after a hot day when the night gets cool.
COOL_NIGHT_MAX = 17.0
HOT_DAY_MIN = 25.0
# Watering: a warm day and next to no rain in the coming two days.
WATERING_HOURS = 48
WATERING_MAX_RAIN = 2.0
WATERING_MIN_HIGH = 20.0


def drying_window(snap: ForecastSnapshot) -> dict | None:
    """The longest run of dry hours left today between 08:00 and 20:00:
    no precipitation, a low chance of rain and not too cold. None when the
    forecast has no hours left in that part of the day."""
    rain = dict(snap.hourly.get("rre150h0") or [])
    prob = dict(snap.hourly.get("rp0003i0") or [])
    temp = dict(snap.hourly.get("tre200h0") or [])
    now = dt_util.now()
    hour = hour_floor(dt_util.utcnow())
    hours: list[datetime] = []
    while dt_util.as_local(hour).date() == now.date():
        if 8 <= dt_util.as_local(hour).hour < 20 and hour in rain:
            hours.append(hour)
        hour += timedelta(hours=1)
    if not hours:
        return None
    best: list[datetime] = []
    run: list[datetime] = []
    for h in hours:
        dry = (rain.get(h) or 0.0) < RAIN_THRESHOLD_MM and (prob.get(h) is None or prob[h] <= DRYING_MAX_PROBABILITY)
        warm = temp.get(h) is not None and temp[h] >= DRYING_MIN_TEMPERATURE
        if dry and warm and (not run or h - run[-1] == timedelta(hours=1)):
            run.append(h)
        else:
            run = [h] if dry and warm else []
        if len(run) > len(best):
            best = list(run)
    return {
        "hours": len(best),
        "start": dt_util.as_local(best[0]).isoformat() if best else None,
        "end": dt_util.as_local(best[-1] + timedelta(hours=1)).isoformat() if best else None,
    }


def morning_minimum(snap: ForecastSnapshot) -> tuple[datetime, float] | None:
    """The lowest hourly temperature of the coming early morning (04:00 to
    08:00 local; today's while it is not 08:00 yet): (hour, temperature)."""
    temps = snap.hourly.get("tre200h0")
    if not temps:
        return None
    now = dt_util.now()
    day = now.date() if now.hour < WINDSCREEN_HOURS[1] else now.date() + timedelta(days=1)
    start = hour_floor(dt_util.utcnow())
    best: tuple[datetime, float] | None = None
    for ts, v in temps:
        local = dt_util.as_local(ts)
        if v is None or ts < start or local.date() != day or not WINDSCREEN_HOURS[0] <= local.hour <= WINDSCREEN_HOURS[1]:
            continue
        if best is None or v < best[1]:
            best = (ts, v)
    return best


def todays_high(snap: ForecastSnapshot) -> float | None:
    return daily_values(snap, "tre200px").get(dt_util.now().date())


# --- from the station ----------------------------------------------------------


def apparent_temperature(temperature: float | None, humidity: float | None, wind_kmh: float | None) -> float | None:
    """What the air feels like in the shade, all year: the apparent
    temperature of Steadman as the Australian Bureau of Meteorology
    computes it, from air temperature, humidity and wind (no sunshine term).
    AT = T + 0.33 e - 0.70 v - 4.00, e in hPa, v in m/s."""
    if temperature is None or humidity is None or wind_kmh is None:
        return None
    vapour = humidity / 100 * 6.105 * math.exp(17.27 * temperature / (237.7 + temperature))
    return round(temperature + 0.33 * vapour - 0.70 * (wind_kmh / 3.6) - 4.0, 1)


PRESSURE_COLUMNS = ("pp0qffs0", "pp0qnhs0", "prestas0")  # the first the station reports
PRESSURE_STEADY = 1.0  # hPa in three hours
PRESSURE_FAST = 3.0


def pressure_trend(values: dict, earlier: dict | None) -> tuple[float, str] | None:
    """The change of the air pressure over three hours and a word for it:
    (hPa, rising_fast | rising | steady | falling | falling_fast)."""
    if not earlier:
        return None
    for column in PRESSURE_COLUMNS:
        now, before = values.get(column), earlier.get(column)
        if now is not None and before is not None:
            change = round(now - before, 1)
            size = abs(change)
            if size < PRESSURE_STEADY:
                return change, "steady"
            word = "rising" if change > 0 else "falling"
            return change, f"{word}_fast" if size >= PRESSURE_FAST else word
    return None
