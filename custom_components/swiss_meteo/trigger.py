"""Triggers for Swiss Meteo in the automation editor: rain expected, dry
again, frost tonight, new forecast run, official warning issued or cleared. Each targets the integration's own
entities; a target that expands to other entities (an area, say) is
narrowed to the ones this integration created.

The trigger platform API arrived in Home Assistant 2026.10. On an older
version the module still imports, but offers no triggers.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorDeviceClass,
)
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

try:
    from homeassistant.helpers.automation import DomainSpec
    from homeassistant.helpers.trigger import (
        EntityTriggerBase,
        Trigger,
        make_entity_target_state_trigger,
    )
except ImportError:  # Home Assistant before 2026.10: no trigger platform API
    TRIGGERS: dict = {}
else:
    RAIN_SPECS = {BINARY_SENSOR_DOMAIN: DomainSpec(device_class=BinarySensorDeviceClass.MOISTURE)}
    FROST_SPECS = {BINARY_SENSOR_DOMAIN: DomainSpec(device_class=BinarySensorDeviceClass.COLD)}
    RUN_SPECS = {SENSOR_DOMAIN: DomainSpec(device_class=SensorDeviceClass.TIMESTAMP)}
    WARN_SPECS = {BINARY_SENSOR_DOMAIN: DomainSpec(device_class=BinarySensorDeviceClass.SAFETY)}

    def _own_entities(hass: HomeAssistant, entities: set[str], suffix: str | None = None) -> set[str]:
        """Keep only entities created by this integration (and, given a
        suffix, only the one whose unique id ends with it)."""
        registry = er.async_get(hass)
        out = set()
        for entity_id in entities:
            entry = registry.async_get(entity_id)
            if entry is None or entry.platform != DOMAIN:
                continue
            if suffix and not (entry.unique_id or "").endswith(suffix):
                continue
            out.add(entity_id)
        return out

    class _RainExpected(make_entity_target_state_trigger(RAIN_SPECS, STATE_ON)):
        """Rain expected within the next hours: the rain sensor turns on."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_rain_expected")

    class _RainCleared(make_entity_target_state_trigger(RAIN_SPECS, STATE_OFF)):
        """No rain expected any more: the rain sensor turns off."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_rain_expected")

    class _RainStarting(make_entity_target_state_trigger(RAIN_SPECS, STATE_ON)):
        """Radar: rain is about to reach the point (within 30 minutes) or has started."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_rain_approaching")

    class _RainStarted(make_entity_target_state_trigger(RAIN_SPECS, STATE_ON)):
        """Radar: it starts raining at the point."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_raining")

    class _RainStopped(make_entity_target_state_trigger(RAIN_SPECS, STATE_OFF)):
        """Radar: the rain at the point has stopped."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_raining")

    class _FrostExpected(make_entity_target_state_trigger(FROST_SPECS, STATE_ON)):
        """Frost expected tonight: the frost sensor turns on."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities))

    class _WarningIssued(make_entity_target_state_trigger(WARN_SPECS, STATE_ON)):
        """An official warning comes into force: the warning sensor turns on."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_warning_active")

    class _WarningCleared(make_entity_target_state_trigger(WARN_SPECS, STATE_OFF)):
        """No official warning in force any more."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_warning_active")

    class _StrongWindExpected(make_entity_target_state_trigger(WARN_SPECS, STATE_ON)):
        """Gusts above the threshold are forecast for the next hours."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_strong_wind_expected")

    class _StrongWindCleared(make_entity_target_state_trigger(WARN_SPECS, STATE_OFF)):
        """No strong wind expected any more."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_strong_wind_expected")

    class _NewForecast(EntityTriggerBase):
        """A new forecast run has been read (the run sensor changes)."""

        _domain_specs = RUN_SPECS

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_forecast_run")

    TRIGGERS: dict[str, type[Trigger]] = {
        "rain_expected": _RainExpected,
        "rain_cleared": _RainCleared,
        "frost_expected": _FrostExpected,
        "new_forecast": _NewForecast,
        "warning_issued": _WarningIssued,
        "warning_cleared": _WarningCleared,
        "rain_starting": _RainStarting,
        "rain_started": _RainStarted,
        "rain_stopped": _RainStopped,
        "strong_wind_expected": _StrongWindExpected,
        "strong_wind_cleared": _StrongWindCleared,
    }


async def async_get_triggers(hass: HomeAssistant) -> dict:
    """Return the triggers of this integration."""
    return TRIGGERS
