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
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
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

    _GAP = (STATE_UNAVAILABLE, STATE_UNKNOWN)

    class _AcrossGaps:
        """Lets a target-state trigger see a change that follows a gap.

        The core skips every change out of "unavailable" or "unknown". While
        the source cannot be reached the entities are unavailable, so
        whatever began during the outage would switch an entity from
        unavailable straight to its new state, and the core would not fire.
        Such a change is let through here and judged against the last state
        seen before the gap: it fires when that state was not already the
        target. With nothing known from before the gap, a trigger that
        announces something (`_fire_without_history`) fires, the others
        stay quiet. The core asks is_valid_state for every state with a
        value and only then is_valid_transition, so the states are
        remembered there.
        """

        _excluded_from_states = frozenset()
        _fire_without_history = False

        def __init__(self, hass: HomeAssistant, config) -> None:
            super().__init__(hass, config)
            self._last_state: dict[str, str] = {}
            self._previous_state: dict[str, str | None] = {}

        def entity_filter(self, entities: set[str]) -> set[str]:
            # Start from what the entities show now, so that a gap right
            # after the automation starts is judged against a known state.
            kept = super().entity_filter(entities)
            for entity_id in kept:
                state = self._hass.states.get(entity_id)
                if entity_id not in self._last_state and state is not None and state.state not in _GAP:
                    self._last_state[entity_id] = state.state
            return kept

        def is_valid_state(self, state, report_not_triggered) -> bool:
            self._previous_state[state.entity_id] = self._last_state.get(state.entity_id)
            self._last_state[state.entity_id] = state.state
            return super().is_valid_state(state, report_not_triggered)

        def is_valid_transition(self, from_state, to_state) -> bool:
            if from_state.state not in _GAP:
                return super().is_valid_transition(from_state, to_state)
            before = self._previous_state.get(to_state.entity_id)
            if before is None:
                return self._fire_without_history
            return before not in self._to_states

    class _RainExpected(_AcrossGaps, make_entity_target_state_trigger(RAIN_SPECS, STATE_ON)):
        """Rain expected within the next hours: the rain sensor turns on."""

        _fire_without_history = True

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_rain_expected")

    class _RainCleared(_AcrossGaps, make_entity_target_state_trigger(RAIN_SPECS, STATE_OFF)):
        """No rain expected any more: the rain sensor turns off."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_rain_expected")

    class _RainStarting(_AcrossGaps, make_entity_target_state_trigger(RAIN_SPECS, STATE_ON)):
        """Radar: rain is about to reach the point (within 30 minutes) or has started."""

        _fire_without_history = True

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_rain_approaching")

    class _RainStarted(_AcrossGaps, make_entity_target_state_trigger(RAIN_SPECS, STATE_ON)):
        """Radar: it starts raining at the point."""

        _fire_without_history = True

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_raining")

    class _RainStopped(_AcrossGaps, make_entity_target_state_trigger(RAIN_SPECS, STATE_OFF)):
        """Radar: the rain at the point has stopped."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_raining")

    class _FrostExpected(_AcrossGaps, make_entity_target_state_trigger(FROST_SPECS, STATE_ON)):
        """Frost expected tonight: the frost sensor turns on."""

        _fire_without_history = True

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities))

    class _WarningIssued(_AcrossGaps, make_entity_target_state_trigger(WARN_SPECS, STATE_ON)):
        """An official warning comes into force: the warning sensor turns on."""

        _fire_without_history = True

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_warning_active")

    class _WarningCleared(_AcrossGaps, make_entity_target_state_trigger(WARN_SPECS, STATE_OFF)):
        """No official warning in force any more."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_warning_active")

    class _StrongWindExpected(_AcrossGaps, make_entity_target_state_trigger(WARN_SPECS, STATE_ON)):
        """Gusts above the threshold are forecast for the next hours."""

        _fire_without_history = True

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_strong_wind_expected")

    class _StrongWindCleared(_AcrossGaps, make_entity_target_state_trigger(WARN_SPECS, STATE_OFF)):
        """No strong wind expected any more."""

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_strong_wind_expected")

    class _NewForecast(EntityTriggerBase):
        """A new forecast run has been read (the run sensor changes).

        After a gap it fires when the run differs from the one seen before
        it; a run that only reappears does not fire again."""

        _domain_specs = RUN_SPECS
        _excluded_from_states = frozenset()

        def __init__(self, hass: HomeAssistant, config) -> None:
            super().__init__(hass, config)
            self._last_run: dict[str, str] = {}
            self._previous_run: dict[str, str | None] = {}

        def entity_filter(self, entities: set[str]) -> set[str]:
            return _own_entities(self._hass, super().entity_filter(entities), "_forecast_run")

        def is_valid_state(self, state: State, report_not_triggered) -> bool:
            self._previous_run[state.entity_id] = self._last_run.get(state.entity_id)
            self._last_run[state.entity_id] = state.state
            return True

        def is_valid_transition(self, from_state: State, to_state: State) -> bool:
            if from_state.state in _GAP:
                before = self._previous_run.get(to_state.entity_id)
                return before is not None and before != to_state.state
            return from_state.state != to_state.state

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
