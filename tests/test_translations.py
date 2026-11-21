"""Entity names and icons come from the translation files: every entity
has a name in each language, the icon file knows only entities that exist,
and Home Assistant shows the names in the instance language."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.swiss_meteo.const import DOMAIN

from .feeds import entity, setup_everything

COMPONENT = Path(__file__).parent.parent / "custom_components" / DOMAIN
LANGUAGES = ("de", "en", "fr", "it")


def _read(name: str) -> dict:
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


STRINGS = _read("strings.json")
ICONS = _read("icons.json")


def _keys(tree: dict, prefix: str = "") -> set[str]:
    """Every leaf of a translation tree as a dotted path."""
    found: set[str] = set()
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        found |= _keys(value, path) if isinstance(value, dict) else {path}
    return found


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_language_has_every_text(language: str) -> None:
    translated = _read(f"translations/{language}.json")
    assert _keys(translated["entity"]) == _keys(STRINGS["entity"])
    assert _keys(translated["exceptions"]) == _keys(STRINGS["exceptions"])


def test_english_file_is_the_strings_file() -> None:
    assert _read("translations/en.json") == STRINGS


def test_icons_belong_to_entities_that_have_a_name() -> None:
    for platform, entries in ICONS["entity"].items():
        for key, icon in entries.items():
            assert key in STRINGS["entity"][platform], key
            assert icon["default"].startswith("mdi:"), key
            for state in icon.get("state", {}):
                assert state in STRINGS["entity"][platform][key]["state"], (key, state)


def test_warning_level_icon_follows_the_level() -> None:
    assert ICONS["entity"]["sensor"]["warning_level"] == {"default": "mdi:alert", "state": {"none": "mdi:alert-outline"}}


async def test_every_entity_is_named_from_the_translation_file(hass: HomeAssistant, setup_integration, all_entities_enabled) -> None:
    entry = await setup_everything(hass, setup_integration)
    entries = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    named = [item for item in entries if item.domain != "weather"]
    assert len(named) > 60
    for item in named:
        texts = STRINGS["entity"][item.domain]
        assert item.translation_key in texts, item.entity_id
        assert item.original_name == texts[item.translation_key]["name"], item.entity_id
        assert item.original_icon is None, item.entity_id
    assert hass.states.get(entity("sensor", "temperature")).attributes["friendly_name"].endswith(" Temperature")
    # the weather entity is the device's main entity and carries its name
    weather = next(item for item in entries if item.domain == "weather")
    assert weather.original_name is None


async def test_names_follow_the_instance_language(hass: HomeAssistant, setup_integration) -> None:
    hass.config.language = "de"
    await setup_everything(hass, setup_integration)
    assert hass.states.get(entity("sensor", "dew_point")).attributes["friendly_name"] == "Wetter Zürich Taupunkt"
    assert hass.states.get(entity("binary_sensor", "rain_expected")).attributes["friendly_name"] == "Wetter Zürich Regen erwartet"
    assert hass.states.get(entity("image", "radar")).attributes["friendly_name"] == "Wetter Zürich Radarbild"
