"""The diagnostics download: complete enough to look into a problem,
without the place it belongs to."""
from __future__ import annotations

import json
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.swiss_meteo.const import USER_AGENT
from custom_components.swiss_meteo.diagnostics import async_get_config_entry_diagnostics

from .conftest import NOW, RUN, make_entry
from .feeds import setup_everything
from .test_open_meteo import FETCH, make_data

REDACTED = "**REDACTED**"


async def test_everything_loaded(hass: HomeAssistant, setup_integration) -> None:
    with patch(FETCH, return_value=make_data()):
        entry = await setup_everything(hass, setup_integration, open_meteo=True)
    dump = await async_get_config_entry_diagnostics(hass, entry)

    assert dump["integration"] == USER_AGENT
    assert dump["entry"]["title"] == REDACTED
    assert dump["entry"]["unique_id"] == REDACTED
    data = dump["entry"]["data"]
    assert [data[key] for key in ("point_lat", "point_lon", "point_name", "point_id")] == [REDACTED] * 4
    assert (data["station"], data["radar"]) == ("SMA", True)
    # neither the place nor its coordinates are anywhere in the file
    text = json.dumps(dump, default=str, ensure_ascii=False)
    for private in ("Zürich", "47.3769", "8.5417", "800100"):
        assert private not in text, private

    forecast = dump["forecast"]
    assert forecast["loaded"] is True and forecast["last_update_success"] is True
    assert forecast["run"] == RUN.isoformat()
    assert forecast["missing"] == []
    assert forecast["requests_today"] > 0 and forecast["bytes_today"] > 0
    assert forecast["daily"]["tre200px"]["rows"] == 8
    assert forecast["hourly"]["tre200h0"]["rows"] == 72
    assert forecast["hourly"]["tre200h0"]["sample"][0] == (RUN.isoformat(), 5.0)

    assert dump["station"]["configured"] == "SMA"
    assert dump["station"]["fresh"] is True
    assert dump["station"]["values"]["tre200s0"] == 7.5
    assert dump["pollen"]["configured"] == "PZH"
    assert dump["pollen"]["current"] == {"birch": 30.0, "grasses": 2.0}
    assert dump["warnings"]["enabled"] is True
    assert dump["warnings"]["feed_alerts"] == 2
    assert [item["level"] for item in dump["warnings"]["matching"]] == ["yellow", "red"]
    assert dump["radar"]["enabled"] is True
    assert (dump["radar"]["rate"], dump["radar"]["eta_min"]) == (1.5, 0)
    assert dump["open_meteo"]["enabled"] is True
    assert dump["open_meteo"]["fetched"] == NOW.isoformat()
    assert dump["open_meteo"]["hours"] > 0
    assert "european_aqi" in dump["open_meteo"]["current"]


async def test_forecast_alone(hass: HomeAssistant, setup_integration) -> None:
    entry = await setup_integration()
    dump = await async_get_config_entry_diagnostics(hass, entry)
    assert dump["forecast"]["loaded"] is True
    assert dump["station"] == {"configured": None, "last_update_success": None, "timestamp": None, "fresh": None, "values": None}
    assert dump["pollen"]["configured"] is None
    assert dump["warnings"]["enabled"] is False and dump["warnings"]["matching"] is None
    assert dump["radar"]["enabled"] is False and dump["radar"]["frame_time"] is None
    assert dump["open_meteo"]["enabled"] is False and dump["open_meteo"]["current"] is None


async def test_entry_that_is_not_loaded(hass: HomeAssistant) -> None:
    entry = make_entry(hass)
    dump = await async_get_config_entry_diagnostics(hass, entry)
    assert dump["forecast"]["loaded"] is False
    assert dump["forecast"]["run"] is None and dump["forecast"]["hourly"] is None
    assert dump["entry"]["data"]["point_name"] == REDACTED
    assert dump["radar"]["enabled"] is False
