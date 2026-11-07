"""MeteoSwiss weather symbol codes mapped to Home Assistant conditions.

The local forecast carries the symbol as an integer: day codes 1-42, night
codes 101-142. The night codes have meanings of their own (101 is "clear",
126 is "high cloud" where day code 26 is "high clouds" with sun), so each
code is listed on its own. The pictures MeteoSwiss draws for these codes
are proprietary; the numbers and their meaning are open data, which is all
this table uses.
"""
from __future__ import annotations

from homeassistant.components.weather import (
    ATTR_CONDITION_CLEAR_NIGHT,
    ATTR_CONDITION_CLOUDY,
    ATTR_CONDITION_FOG,
    ATTR_CONDITION_LIGHTNING,
    ATTR_CONDITION_LIGHTNING_RAINY,
    ATTR_CONDITION_PARTLYCLOUDY,
    ATTR_CONDITION_POURING,
    ATTR_CONDITION_RAINY,
    ATTR_CONDITION_SNOWY,
    ATTR_CONDITION_SNOWY_RAINY,
    ATTR_CONDITION_SUNNY,
)

_SUNNY = ATTR_CONDITION_SUNNY
_CLEAR = ATTR_CONDITION_CLEAR_NIGHT
_PARTLY = ATTR_CONDITION_PARTLYCLOUDY
_CLOUDY = ATTR_CONDITION_CLOUDY
_FOG = ATTR_CONDITION_FOG
_RAINY = ATTR_CONDITION_RAINY
_POURING = ATTR_CONDITION_POURING
_SNOWY = ATTR_CONDITION_SNOWY
_SLEET = ATTR_CONDITION_SNOWY_RAINY
_LIGHTNING = ATTR_CONDITION_LIGHTNING
_STORM = ATTR_CONDITION_LIGHTNING_RAINY

# code -> (condition, short English meaning)
SYMBOLS: dict[int, tuple[str, str]] = {
    1: (_SUNNY, "sunny"),
    2: (_PARTLY, "mostly sunny, some clouds"),
    3: (_PARTLY, "partly sunny, thick passing clouds"),
    4: (_CLOUDY, "overcast"),
    5: (_CLOUDY, "very cloudy"),
    6: (_RAINY, "sunny intervals, isolated showers"),
    7: (_SLEET, "sunny intervals, isolated sleet"),
    8: (_SNOWY, "sunny intervals, snow showers"),
    9: (_RAINY, "overcast, some rain showers"),
    10: (_SLEET, "overcast, some sleet"),
    11: (_SNOWY, "overcast, some snow showers"),
    12: (_LIGHTNING, "sunny intervals, chance of thunderstorms"),
    13: (_STORM, "sunny intervals, possible thunderstorms"),
    14: (_RAINY, "very cloudy, light rain"),
    15: (_SLEET, "very cloudy, light sleet"),
    16: (_SNOWY, "very cloudy, light snow showers"),
    17: (_RAINY, "very cloudy, intermittent rain"),
    18: (_SLEET, "very cloudy, intermittent sleet"),
    19: (_SNOWY, "very cloudy, intermittent snow"),
    20: (_POURING, "very overcast with rain"),
    21: (_SLEET, "very overcast with frequent sleet"),
    22: (_SNOWY, "very overcast with heavy snow"),
    23: (_STORM, "very overcast, slight chance of storms"),
    24: (_STORM, "very overcast with storms"),
    25: (_STORM, "very cloudy, very stormy"),
    26: (_SUNNY, "high clouds"),
    27: (_FOG, "stratus"),
    28: (_FOG, "fog"),
    29: (_RAINY, "sunny intervals, scattered showers"),
    30: (_SNOWY, "sunny intervals, scattered snow showers"),
    31: (_SLEET, "sunny intervals, scattered sleet"),
    32: (_STORM, "sunny intervals, some showers with thunder"),
    33: (_RAINY, "short sunny intervals, frequent rain"),
    34: (_SNOWY, "short sunny intervals, frequent snowfalls"),
    35: (_CLOUDY, "overcast and dry"),
    36: (_LIGHTNING, "partly sunny, slightly stormy"),
    37: (_SNOWY, "partly sunny, stormy snow showers"),
    38: (_STORM, "overcast, thundery showers"),
    39: (_SLEET, "overcast, thundery snow showers"),
    40: (_LIGHTNING, "very cloudy, slightly stormy"),
    41: (_LIGHTNING, "overcast, slightly stormy"),
    42: (_SNOWY, "very cloudy, thundery snow showers"),
    101: (_CLEAR, "clear"),
    102: (_PARTLY, "slightly overcast"),
    103: (_PARTLY, "heavy cloud formations"),
    104: (_CLOUDY, "overcast"),
    105: (_CLOUDY, "very cloudy"),
    106: (_RAINY, "overcast, scattered showers"),
    107: (_SLEET, "overcast, scattered rain and snow showers"),
    108: (_SNOWY, "overcast, snow showers"),
    109: (_RAINY, "overcast, some showers"),
    110: (_SLEET, "overcast, some rain and snow showers"),
    111: (_SNOWY, "overcast, some snow showers"),
    112: (_LIGHTNING, "slightly stormy"),
    113: (_STORM, "storms"),
    114: (_RAINY, "very cloudy, light rain"),
    115: (_SLEET, "very cloudy, light rain and snow showers"),
    116: (_SNOWY, "very cloudy, light snowfall"),
    117: (_RAINY, "very cloudy, intermittent rain"),
    118: (_SLEET, "very cloudy, intermittent mixed rain and snowfall"),
    119: (_SNOWY, "very cloudy, intermittent snowfall"),
    120: (_POURING, "very cloudy, constant rain"),
    121: (_SLEET, "very cloudy, frequent rain and snowfall"),
    122: (_SNOWY, "very cloudy, heavy snowfall"),
    123: (_STORM, "very cloudy, slightly stormy"),
    124: (_STORM, "very cloudy, stormy"),
    125: (_STORM, "very cloudy, storms"),
    126: (_CLOUDY, "high cloud"),
    127: (_FOG, "stratus"),
    128: (_FOG, "fog"),
    129: (_RAINY, "slightly overcast, scattered showers"),
    130: (_SNOWY, "slightly overcast, scattered snowfall"),
    131: (_SLEET, "slightly overcast, rain and snow showers"),
    132: (_STORM, "slightly overcast, some showers with thunder"),
    133: (_RAINY, "overcast, frequent rain showers"),
    134: (_SNOWY, "overcast, frequent snow showers"),
    135: (_CLOUDY, "overcast and dry"),
    136: (_LIGHTNING, "slightly overcast, slightly stormy"),
    137: (_SNOWY, "slightly overcast, stormy snow showers"),
    138: (_STORM, "overcast, thundery showers"),
    139: (_SLEET, "overcast, thundery snow showers"),
    140: (_LIGHTNING, "very cloudy, slightly stormy"),
    141: (_LIGHTNING, "overcast, slightly stormy"),
    142: (_SNOWY, "very cloudy, thundery snow showers"),
}


def condition_for(code: float | int | None, daytime: bool | None = None) -> str | None:
    """The Home Assistant condition of a symbol code. With `daytime`, a day
    code shown at night (or a night code by day) is swapped for its
    counterpart first — the hourly symbol keeps its night variant for a
    while after sunrise, and the daily symbol is a day code by definition."""
    if code is None:
        return None
    try:
        code = int(code)
    except (TypeError, ValueError):
        return None
    if daytime is True and code > 100:
        code -= 100
    elif daytime is False and 0 < code <= 100:
        code += 100
    entry = SYMBOLS.get(code)
    return entry[0] if entry else None


def meaning_for(code: float | int | None) -> str | None:
    try:
        entry = SYMBOLS.get(int(code)) if code is not None else None
    except (TypeError, ValueError):
        return None
    return entry[1] if entry else None
