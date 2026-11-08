"""Unit tests of the MeteoSwiss symbol code mapping."""
from __future__ import annotations

from custom_components.swiss_meteo.symbols import SYMBOLS, condition_for, meaning_for


def test_every_day_code_has_a_night_counterpart() -> None:
    day_codes = {c for c in SYMBOLS if 0 < c <= 100}
    assert day_codes, "symbol table is empty"
    for code in day_codes:
        assert code + 100 in SYMBOLS, f"night code for {code} missing"


def test_condition_for_swaps_day_and_night_codes() -> None:
    code = min(c for c in SYMBOLS if 0 < c <= 100)
    assert condition_for(code) == SYMBOLS[code][0]
    # a day code shown at night takes the night symbol's condition
    assert condition_for(code, daytime=False) == SYMBOLS[code + 100][0]
    # a night code by day takes the day symbol's condition
    assert condition_for(code + 100, daytime=True) == SYMBOLS[code][0]


def test_condition_for_tolerates_floats_none_and_unknown_codes() -> None:
    code = min(c for c in SYMBOLS if 0 < c <= 100)
    assert condition_for(float(code)) == SYMBOLS[code][0]
    assert condition_for(None) is None
    assert condition_for(9999) is None
    assert condition_for("x") is None


def test_meaning_for_returns_text_or_none() -> None:
    assert meaning_for(128) == "fog"
    assert meaning_for(None) is None
    assert meaning_for("x") is None
