"""Device texts (name, manufacturer, model) in German, French, Italian
and English, keyed by the instance language, with English as the
fallback. They carry the place and the stations, so they are put
together here; entity names, icons and every other text are in the
translation files."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

SUPPORTED_LANGUAGES = ("de", "en", "fr", "it")

STRINGS: dict[str, dict[str, str]] = {
    "device_name": {
        "de": "Wetter {place}",
        "en": "Weather {place}",
        "fr": "Météo {place}",
        "it": "Meteo {place}",
    },
    "manufacturer": {
        "de": "Bundesamt für Meteorologie und Klimatologie MeteoSchweiz",
        "en": "Federal Office of Meteorology and Climatology MeteoSwiss",
        "fr": "Office fédéral de météorologie et de climatologie MétéoSuisse",
        "it": "Ufficio federale di meteorologia e climatologia MeteoSvizzera",
    },
    "model": {
        "de": "Lokalprognose + Station {station} (Open Data)",
        "en": "Local forecast + station {station} (Open Data)",
        "fr": "Prévision locale + station {station} (Open Data)",
        "it": "Previsione locale + stazione {station} (Open Data)",
    },
    "model_no_station": {
        "de": "Lokalprognose (Open Data)",
        "en": "Local forecast (Open Data)",
        "fr": "Prévision locale (Open Data)",
        "it": "Previsione locale (Open Data)",
    },
    "device_name_open_meteo": {
        "de": "Open-Meteo {place}",
        "en": "Open-Meteo {place}",
        "fr": "Open-Meteo {place}",
        "it": "Open-Meteo {place}",
    },
    "model_open_meteo": {
        "de": "Luftqualität, UV-Index, Pollenprognose (CAMS-Modell, nicht amtlich)",
        "en": "Air quality, UV index, pollen forecast (CAMS model, not official)",
        "fr": "Qualité de l'air, indice UV, prévision pollinique (modèle CAMS, non officiel)",
        "it": "Qualità dell'aria, indice UV, previsione pollini (modello CAMS, non ufficiale)",
    },
    "model_precip": {
        "de": "{station}, Niederschlag {precip}",
        "en": "{station}, precipitation {precip}",
        "fr": "{station}, précipitations {precip}",
        "it": "{station}, precipitazioni {precip}",
    },
    "model_pollen": {
        "de": "{station}, Pollen {pollen}",
        "en": "{station}, pollen {pollen}",
        "fr": "{station}, pollen {pollen}",
        "it": "{station}, pollini {pollen}",
    },
}


def get_language(hass: HomeAssistant) -> str:
    lang = (hass.config.language or "en").split("-")[0].lower()
    return lang if lang in SUPPORTED_LANGUAGES else "en"


def t(key: str, hass: HomeAssistant, **kwargs) -> str:
    """A localized string, formatted with the keyword arguments."""
    lang = get_language(hass)
    template = STRINGS.get(key, {}).get(lang) or STRINGS.get(key, {}).get("en") or key
    return template.format(**kwargs) if kwargs else template
