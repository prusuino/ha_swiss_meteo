"""The triggers across a gap without a value, with real automations on
registered entities whose state is set by hand: what begins while
MeteoSwiss cannot be reached still fires, what was already on does not fire
a second time, and "cleared" needs something that was on before."""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.swiss_meteo.const import DOMAIN

# trigger -> (entity domain, device class, unique id suffix, the state it waits for)
ANNOUNCING = {
    "warning_issued": ("binary_sensor", "safety", "_warning_active"),
    "strong_wind_expected": ("binary_sensor", "safety", "_strong_wind_expected"),
    "rain_expected": ("binary_sensor", "moisture", "_rain_expected"),
    "rain_starting": ("binary_sensor", "moisture", "_rain_approaching"),
    "rain_started": ("binary_sensor", "moisture", "_raining"),
    "frost_expected": ("binary_sensor", "cold", "_frost_expected"),
}
CLEARING = {
    "warning_cleared": ("binary_sensor", "safety", "_warning_active"),
    "strong_wind_cleared": ("binary_sensor", "safety", "_strong_wind_expected"),
    "rain_cleared": ("binary_sensor", "moisture", "_rain_expected"),
    "rain_stopped": ("binary_sensor", "moisture", "_raining"),
}


def _entity(hass: HomeAssistant, domain: str, device_class: str, suffix: str) -> str:
    return er.async_get(hass).async_get_or_create(
        domain, DOMAIN, f"entry{suffix}", suggested_object_id=f"meteo{suffix}", original_device_class=device_class).entity_id


async def _play(hass: HomeAssistant, entity_id: str, device_class: str, *states: str) -> None:
    for state in states:
        hass.states.async_set(entity_id, state, {"device_class": device_class})
        await hass.async_block_till_done()


async def _automation(hass: HomeAssistant, name: str, entity_id: str) -> list:
    calls = async_mock_service(hass, "test", name)
    assert await async_setup_component(hass, "automation", {"automation": {
        "alias": name, "trigger": {"trigger": f"swiss_meteo.{name}", "target": {"entity_id": entity_id}},
        "action": {"action": f"test.{name}"},
    }})
    await hass.async_block_till_done()
    assert hass.states.get(f"automation.{name}") is not None, "the automation was rejected"
    return calls


@pytest.mark.parametrize("name", list(ANNOUNCING))
async def test_what_begins_during_an_outage_fires(hass: HomeAssistant, enable_custom_integrations, name) -> None:
    domain, device_class, suffix = ANNOUNCING[name]
    entity = _entity(hass, domain, device_class, suffix)
    await _play(hass, entity, device_class, "off")
    calls = await _automation(hass, name, entity)
    await _play(hass, entity, device_class, "on")
    assert len(calls) == 1
    await _play(hass, entity, device_class, "unavailable", "on")  # the same warning after an outage
    assert len(calls) == 1
    await _play(hass, entity, device_class, "off", "unavailable", "on")  # it began during the outage
    assert len(calls) == 2


@pytest.mark.parametrize("name", list(ANNOUNCING))
async def test_nothing_known_before_the_outage_still_announces(hass: HomeAssistant, enable_custom_integrations, name) -> None:
    domain, device_class, suffix = ANNOUNCING[name]
    entity = _entity(hass, domain, device_class, suffix)
    await _play(hass, entity, device_class, "unavailable")
    calls = await _automation(hass, name, entity)
    await _play(hass, entity, device_class, "off")
    assert len(calls) == 0
    await _play(hass, entity, device_class, "unknown", "on")  # off before the gap
    assert len(calls) == 1


@pytest.mark.parametrize("name", list(CLEARING))
async def test_cleared_needs_something_that_was_on(hass: HomeAssistant, enable_custom_integrations, name) -> None:
    domain, device_class, suffix = CLEARING[name]
    entity = _entity(hass, domain, device_class, suffix)
    await _play(hass, entity, device_class, "unavailable")
    calls = await _automation(hass, name, entity)
    await _play(hass, entity, device_class, "off")  # nothing known from before
    assert len(calls) == 0
    await _play(hass, entity, device_class, "on", "off")
    assert len(calls) == 1
    await _play(hass, entity, device_class, "on", "unavailable", "off")  # it ended during the outage
    assert len(calls) == 2
    await _play(hass, entity, device_class, "unavailable", "off")
    assert len(calls) == 2


async def test_new_forecast(hass: HomeAssistant, enable_custom_integrations) -> None:
    run = _entity(hass, "sensor", "timestamp", "_forecast_run")
    await _play(hass, run, "timestamp", "unavailable")
    calls = await _automation(hass, "new_forecast", run)
    await _play(hass, run, "timestamp", "2026-11-23T12:00:00+00:00")  # nothing known from before
    assert len(calls) == 0
    await _play(hass, run, "timestamp", "2026-11-23T13:00:00+00:00")
    assert len(calls) == 1
    await _play(hass, run, "timestamp", "unavailable", "2026-11-23T13:00:00+00:00")  # the same run again
    assert len(calls) == 1
    await _play(hass, run, "timestamp", "unavailable", "2026-11-23T15:00:00+00:00")  # a newer run after the outage
    assert len(calls) == 2
