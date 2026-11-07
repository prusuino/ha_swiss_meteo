"""Diagnostics download: the entry's configuration, what the last reads
cost, which parameters were read and the newest values — enough to check
a forecast problem without the coordinates leaving the file unredacted."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_POINT_LAT, CONF_POINT_LON, DOMAIN, USER_AGENT
from .coordinator import EntryData


def _series_summary(series: dict) -> dict[str, Any]:
    return {
        param: {
            "rows": len(values),
            "first": values[0][0].isoformat() if values else None,
            "last": values[-1][0].isoformat() if values else None,
            "sample": [(ts.isoformat(), v) for ts, v in values[:3]],
        }
        for param, values in series.items()
    }


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    data: EntryData | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    snap = data.forecast.data if data and data.forecast.data else None
    station = data.station if data else None
    return {
        "integration": USER_AGENT,
        "entry": {
            "title": "**REDACTED**",
            "unique_id": "**REDACTED**" if entry.unique_id else None,
            "data": {k: ("**REDACTED**" if k in (CONF_POINT_LAT, CONF_POINT_LON) else v) for k, v in entry.data.items()},
            "options": dict(entry.options),
        },
        "forecast": {
            "loaded": data is not None,
            "last_update_success": data.forecast.last_update_success if data else None,
            "run": snap.run.isoformat() if snap and snap.run else None,
            "daily_fetched": snap.daily_fetched.isoformat() if snap and snap.daily_fetched else None,
            "hourly_fetched": snap.hourly_fetched.isoformat() if snap and snap.hourly_fetched else None,
            "missing": snap.missing if snap else None,
            "requests_today": snap.requests_today if snap else None,
            "bytes_today": snap.bytes_today if snap else None,
            "daily": _series_summary(snap.daily) if snap else None,
            "hourly": _series_summary(snap.hourly) if snap else None,
        },
        "station": {
            "configured": station.station if station else None,
            "last_update_success": station.last_update_success if station else None,
            "timestamp": station.data.timestamp.isoformat() if station and station.data else None,
            "fresh": station.fresh if station else None,
            "values": station.data.values if station and station.data else None,
        },
    }
