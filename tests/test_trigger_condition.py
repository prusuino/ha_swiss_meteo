"""Triggers and conditions for the automation editor: each one keeps
exactly its own entity out of whatever the target expands to."""
from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.swiss_meteo import condition, trigger

from .feeds import entity, setup_everything

TRIGGER_ENTITY = {
    "rain_expected": ("binary_sensor", "rain_expected"),
    "rain_cleared": ("binary_sensor", "rain_expected"),
    "rain_starting": ("binary_sensor", "rain_approaching"),
    "rain_started": ("binary_sensor", "raining"),
    "rain_stopped": ("binary_sensor", "raining"),
    "frost_expected": ("binary_sensor", "frost_tonight"),
    "warning_issued": ("binary_sensor", "warning_active"),
    "warning_cleared": ("binary_sensor", "warning_active"),
    "strong_wind_expected": ("binary_sensor", "strong_wind_expected"),
    "strong_wind_cleared": ("binary_sensor", "strong_wind_expected"),
    "new_forecast": ("sensor", "forecast_run"),
}

CONDITION_ENTITY = {
    "is_rain_expected": ("binary_sensor", "rain_expected"),
    "is_dry": ("binary_sensor", "rain_expected"),
    "is_raining": ("binary_sensor", "raining"),
    "is_not_raining": ("binary_sensor", "raining"),
    "is_rain_approaching": ("binary_sensor", "rain_approaching"),
    "is_frost_expected": ("binary_sensor", "frost_tonight"),
    "is_warning_active": ("binary_sensor", "warning_active"),
    "is_strong_wind_expected": ("binary_sensor", "strong_wind_expected"),
}

# Entities of other integrations with the same device classes, as an area
# would bring them along: one known to the registry, one a bare state.
FOREIGN = (
    ("binary_sensor", "moisture", "leak_rain_expected"),
    ("binary_sensor", "cold", "freezer_frost"),
    ("binary_sensor", "safety", "smoke_warning_active"),
    ("sensor", "timestamp", "backup_forecast_run"),
)


def everything_in_the_house(hass: HomeAssistant) -> set[str]:
    registry = er.async_get(hass)
    for domain, device_class, name in FOREIGN:
        registered = registry.async_get_or_create(
            domain, "another_integration", f"other_{name}", suggested_object_id=name, original_device_class=device_class
        )
        hass.states.async_set(registered.entity_id, "on", {"device_class": device_class})
        hass.states.async_set(f"{domain}.loose_{name}", "on", {"device_class": device_class})
    return set(hass.states.async_entity_ids())


def without_init(cls: type, hass: HomeAssistant):
    """A trigger or condition as far as its entity filter needs it."""
    item = cls.__new__(cls)
    item._hass = hass
    return item


async def test_all_of_them_are_offered(hass: HomeAssistant) -> None:
    assert set(await trigger.async_get_triggers(hass)) == set(TRIGGER_ENTITY)
    assert set(await condition.async_get_conditions(hass)) == set(CONDITION_ENTITY)


async def test_each_trigger_keeps_its_own_entity(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    candidates = everything_in_the_house(hass)
    assert len(candidates) > 40
    for key, cls in trigger.TRIGGERS.items():
        assert without_init(cls, hass).entity_filter(candidates) == {entity(*TRIGGER_ENTITY[key])}, key


async def test_each_condition_keeps_its_own_entity(hass: HomeAssistant, setup_integration) -> None:
    await setup_everything(hass, setup_integration)
    candidates = everything_in_the_house(hass)
    for key, cls in condition.CONDITIONS.items():
        assert without_init(cls, hass).entity_filter(candidates) == {entity(*CONDITION_ENTITY[key])}, key


async def test_nothing_of_ours_in_the_target(hass: HomeAssistant) -> None:
    candidates = everything_in_the_house(hass)
    for cls in (*trigger.TRIGGERS.values(), *condition.CONDITIONS.values()):
        assert without_init(cls, hass).entity_filter(candidates) == set()


@pytest.mark.parametrize(("module", "offered"), [(trigger, "TRIGGERS"), (condition, "CONDITIONS")])
def test_an_older_home_assistant_is_offered_nothing(module, offered: str) -> None:
    count = len(getattr(module, offered))
    try:
        with patch.dict(sys.modules, {"homeassistant.helpers.automation": None}):
            importlib.reload(module)
            assert getattr(module, offered) == {}
    finally:
        importlib.reload(module)
    assert len(getattr(module, offered)) == count > 0
