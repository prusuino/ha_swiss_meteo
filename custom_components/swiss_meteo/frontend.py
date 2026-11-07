"""Serving of the bundled dashboard card and its icons.

The files in this integration's frontend/ directory (the card, and the
weather icons it draws) are made reachable under /swiss_meteo_files/.
Adding the card as a Lovelace resource is left to the user — the resource
list is part of the dashboard configuration — and the README shows the
one-time step."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILENAME = "swiss-meteo-card.js"
FILES_URL_BASE = f"/{DOMAIN}_files"
CARD_URL = f"{FILES_URL_BASE}/{CARD_FILENAME}"
_REGISTERED_FLAG = f"{DOMAIN}_files_served"


async def async_serve_frontend(hass: HomeAssistant) -> None:
    """Register the static path once per Home Assistant run. The flag is
    claimed before the await so two entries setting up at once do not
    register twice, and released if the registration raises."""
    if hass.data.get(_REGISTERED_FLAG):
        return
    hass.data[_REGISTERED_FLAG] = True
    frontend_dir = Path(__file__).parent / "frontend"
    registered = False
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(FILES_URL_BASE, str(frontend_dir), cache_headers=False)]
        )
        registered = True
    finally:
        if not registered:
            hass.data.pop(_REGISTERED_FLAG, None)
    _LOGGER.debug("Serving the bundled card at %s", CARD_URL)
