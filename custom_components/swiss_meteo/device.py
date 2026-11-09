"""Device info and entity-id helpers shared by the platforms."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import CONF_POINT_HEIGHT, CONF_POINT_NAME, CONF_POLLEN_STATION, CONF_POLLEN_STATION_NAME, CONF_STATION, CONF_STATION_NAME, DOMAIN, VERSION
from .localization import t

CONFIGURATION_URL = "https://opendatadocs.meteoswiss.ch/e-forecast-data/e4-local-forecast-data"


def entry_suffix(entry: ConfigEntry) -> str:
    """The last four characters of the entry id: keeps the suggested entity
    ids of two entries (two places) apart. Only the id suggested on first
    creation is affected; existing entities keep theirs."""
    return entry.entry_id[-4:].lower()


def place_name(entry: ConfigEntry) -> str:
    return entry.data.get(CONF_POINT_NAME) or "Swiss Meteo"


def device_info(hass: HomeAssistant, entry: ConfigEntry) -> DeviceInfo:
    station = entry.options.get(CONF_STATION_NAME) or entry.data.get(CONF_STATION_NAME) or entry.options.get(CONF_STATION) or entry.data.get(CONF_STATION) or ""
    height = entry.data.get(CONF_POINT_HEIGHT)
    model = t("model", hass, station=station) if station else t("model_no_station", hass)
    pollen = entry.options.get(CONF_POLLEN_STATION_NAME) or entry.data.get(CONF_POLLEN_STATION_NAME) or entry.options.get(CONF_POLLEN_STATION) or entry.data.get(CONF_POLLEN_STATION) or ""
    if pollen:
        model = t("model_pollen", hass, station=model, pollen=pollen)
    if isinstance(height, (int, float)):
        model = f"{model} · {height:.0f} m"
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        sw_version=VERSION,
        name=t("device_name", hass, place=place_name(entry)),
        manufacturer=t("manufacturer", hass),
        model=model,
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=CONFIGURATION_URL,
    )
