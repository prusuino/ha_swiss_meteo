"""Conditions for Swiss Meteo in the automation editor: rain expected or
not within the next hours, frost expected tonight. As with the triggers,
a target that expands to other entities is narrowed to the ones this
integration created.

The condition platform API arrived in Home Assistant 2026.11. On an older
version the module still imports, but offers no conditions.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
)
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

try:
    from homeassistant.helpers.automation import DomainSpec
    from homeassistant.helpers.condition import Condition, make_entity_state_condition
except ImportError:  # Home Assistant before 2026.11: no condition platform API
    CONDITIONS: dict = {}
else:
    RAIN_SPECS = {BINARY_SENSOR_DOMAIN: DomainSpec(device_class=BinarySensorDeviceClass.MOISTURE)}
    FROST_SPECS = {BINARY_SENSOR_DOMAIN: DomainSpec(device_class=BinarySensorDeviceClass.COLD)}

    def _own_entities(hass: HomeAssistant, entities: set[str]) -> set[str]:
        registry = er.async_get(hass)
        return {
            entity_id
            for entity_id in entities
            if (entry := registry.async_get(entity_id)) is not None and entry.platform == DOMAIN
        }

    class _IsRainExpected(make_entity_state_condition(RAIN_SPECS, STATE_ON)):
        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities))

    class _IsDry(make_entity_state_condition(RAIN_SPECS, STATE_OFF)):
        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities))

    class _IsFrostExpected(make_entity_state_condition(FROST_SPECS, STATE_ON)):
        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities))

    CONDITIONS: dict[str, type[Condition]] = {
        "is_rain_expected": _IsRainExpected,
        "is_dry": _IsDry,
        "is_frost_expected": _IsFrostExpected,
    }


async def async_get_conditions(hass: HomeAssistant) -> dict:
    """Return the conditions of this integration."""
    return CONDITIONS
