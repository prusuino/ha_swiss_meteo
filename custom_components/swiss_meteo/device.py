"""Device info and entity-id helpers shared by the platforms."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import (
    CONF_POINT_HEIGHT,
    CONF_POINT_NAME,
    CONF_POLLEN_STATION,
    CONF_POLLEN_STATION_NAME,
    CONF_PRECIP_STATION,
    CONF_PRECIP_STATION_NAME,
    CONF_STATION,
    CONF_STATION_NAME,
    DOMAIN,
    VERSION,
)
from .localization import t

CONFIGURATION_URL = "https://opendatadocs.meteoswiss.ch/e-forecast-data/e4-local-forecast-data"
OPEN_METEO_URL = "https://open-meteo.com/en/docs/air-quality-api"


def entry_suffix(entry: ConfigEntry) -> str:
    """The last four characters of the entry id: keeps the suggested entity
    ids of two entries (two places) apart. Only the id suggested on first
    creation is affected; existing entities keep theirs."""
    return entry.entry_id[-4:].lower()


def place_name(entry: ConfigEntry) -> str:
    return entry.data.get(CONF_POINT_NAME) or "Swiss Meteo"


def station_choice(entry: ConfigEntry, key: str, name_key: str) -> str:
    """The name of a chosen station (its abbreviation when the name is not
    known), "" for none. The Configure dialog writes to the options, and
    they count as a whole: a station switched off there is off, whatever
    the setup had chosen."""
    source = entry.options if key in entry.options else entry.data
    return str(source.get(name_key) or source.get(key) or "")


def device_info(hass: HomeAssistant, entry: ConfigEntry) -> DeviceInfo:
    station = station_choice(entry, CONF_STATION, CONF_STATION_NAME)
    height = entry.data.get(CONF_POINT_HEIGHT)
    model = t("model", hass, station=station) if station else t("model_no_station", hass)
    precip = station_choice(entry, CONF_PRECIP_STATION, CONF_PRECIP_STATION_NAME)
    if precip:
        model = t("model_precip", hass, station=model, precip=precip)
    pollen = station_choice(entry, CONF_POLLEN_STATION, CONF_POLLEN_STATION_NAME)
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


def open_meteo_identifier(entry: ConfigEntry) -> tuple[str, str]:
    return (DOMAIN, f"{entry.entry_id}_open_meteo")


def links_by_device_id() -> bool:
    """Current Home Assistant names the parent of a device by its registry
    id (`via_device_id`); older versions only know its identifier
    (`via_device`), which newer ones report as deprecated."""
    return "via_device_id" in DeviceInfo.__optional_keys__ | DeviceInfo.__required_keys__


def open_meteo_device_info(hass: HomeAssistant, entry: ConfigEntry) -> DeviceInfo:
    """The optional Open-Meteo values get a device of their own, so that
    nobody takes modelled third-party values for MeteoSwiss data."""
    info = DeviceInfo(
        identifiers={open_meteo_identifier(entry)},
        sw_version=VERSION,
        name=t("device_name_open_meteo", hass, place=place_name(entry)),
        manufacturer="Open-Meteo",
        model=t("model_open_meteo", hass),
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=OPEN_METEO_URL,
    )
    main = (DOMAIN, entry.entry_id)
    if links_by_device_id():
        # The id is only known once the main device is registered, and the
        # platforms are set up in no fixed order: registering it here
        # returns the existing device or creates it, as the entities do.
        device = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, **device_info(hass, entry))
        info["via_device_id"] = device.id
    else:
        info["via_device"] = main
    return info
