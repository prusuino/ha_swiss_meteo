"""Runtime strings (entity and device names) in the four national
languages plus English, keyed by the instance language. Home Assistant's
translation files cover the config flow; names assigned in Python are
looked up here, with English as the fallback."""
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
    "weather_name": {
        "de": "Wetter",
        "en": "Weather",
        "fr": "Météo",
        "it": "Meteo",
    },
    # station sensors
    "temperature": {"de": "Temperatur", "en": "Temperature", "fr": "Température", "it": "Temperatura"},
    "temperature_5cm": {"de": "Temperatur 5 cm", "en": "Temperature 5 cm", "fr": "Température 5 cm", "it": "Temperatura 5 cm"},
    "dew_point": {"de": "Taupunkt", "en": "Dew Point", "fr": "Point de rosée", "it": "Punto di rugiada"},
    "humidity": {"de": "Luftfeuchtigkeit", "en": "Humidity", "fr": "Humidité", "it": "Umidità"},
    "pressure_qnh": {"de": "Luftdruck QNH", "en": "Pressure QNH", "fr": "Pression QNH", "it": "Pressione QNH"},
    "pressure_qff": {"de": "Luftdruck QFF", "en": "Pressure QFF", "fr": "Pression QFF", "it": "Pressione QFF"},
    "pressure_station": {"de": "Luftdruck Station", "en": "Pressure Station Level", "fr": "Pression station", "it": "Pressione stazione"},
    "wind_speed": {"de": "Wind", "en": "Wind Speed", "fr": "Vent", "it": "Vento"},
    "wind_gust": {"de": "Böen", "en": "Wind Gust", "fr": "Rafales", "it": "Raffiche"},
    "wind_direction": {"de": "Windrichtung", "en": "Wind Direction", "fr": "Direction du vent", "it": "Direzione del vento"},
    "precipitation": {"de": "Niederschlag 10 min", "en": "Precipitation 10 min", "fr": "Précipitations 10 min", "it": "Precipitazioni 10 min"},
    "sunshine": {"de": "Sonnenschein 10 min", "en": "Sunshine 10 min", "fr": "Ensoleillement 10 min", "it": "Soleggiamento 10 min"},
    "global_radiation": {"de": "Globalstrahlung", "en": "Global Radiation", "fr": "Rayonnement global", "it": "Radiazione globale"},
    "diffuse_radiation": {"de": "Diffusstrahlung", "en": "Diffuse Radiation", "fr": "Rayonnement diffus", "it": "Radiazione diffusa"},
    "snow_depth": {"de": "Schneehöhe", "en": "Snow Depth", "fr": "Hauteur de neige", "it": "Altezza della neve"},
    "wind_chill": {"de": "Windchill", "en": "Wind Chill", "fr": "Refroidissement éolien", "it": "Wind chill"},
    "soil_temperature_5cm": {"de": "Bodentemperatur 5 cm", "en": "Soil Temperature 5 cm", "fr": "Température du sol 5 cm", "it": "Temperatura del suolo 5 cm"},
    "soil_temperature_10cm": {"de": "Bodentemperatur 10 cm", "en": "Soil Temperature 10 cm", "fr": "Température du sol 10 cm", "it": "Temperatura del suolo 10 cm"},
    "soil_temperature_20cm": {"de": "Bodentemperatur 20 cm", "en": "Soil Temperature 20 cm", "fr": "Température du sol 20 cm", "it": "Temperatura del suolo 20 cm"},
    # forecast sensors
    "today_max": {"de": "Heute Höchsttemperatur", "en": "Today High", "fr": "Maximum aujourd'hui", "it": "Massima oggi"},
    "today_min": {"de": "Heute Tiefsttemperatur", "en": "Today Low", "fr": "Minimum aujourd'hui", "it": "Minima oggi"},
    "today_precipitation": {"de": "Heute Niederschlag", "en": "Today Precipitation", "fr": "Précipitations aujourd'hui", "it": "Precipitazioni oggi"},
    "tomorrow_max": {"de": "Morgen Höchsttemperatur", "en": "Tomorrow High", "fr": "Maximum demain", "it": "Massima domani"},
    "tomorrow_min": {"de": "Morgen Tiefsttemperatur", "en": "Tomorrow Low", "fr": "Minimum demain", "it": "Minima domani"},
    "tomorrow_precipitation": {"de": "Morgen Niederschlag", "en": "Tomorrow Precipitation", "fr": "Précipitations demain", "it": "Precipitazioni domani"},
    "zero_degree_level": {"de": "Nullgradgrenze", "en": "Zero-Degree Level", "fr": "Isotherme 0 °C", "it": "Isoterma 0 °C"},
    "forecast_run": {"de": "Prognoselauf", "en": "Forecast Run", "fr": "Cycle de prévision", "it": "Ciclo di previsione"},
    "station_time": {"de": "Messzeit Station", "en": "Station Measurement Time", "fr": "Heure de mesure station", "it": "Ora di misura stazione"},
    "traffic_today": {"de": "Datenverkehr heute", "en": "Data Traffic Today", "fr": "Trafic de données aujourd'hui", "it": "Traffico dati oggi"},
}


def get_language(hass: HomeAssistant) -> str:
    lang = (hass.config.language or "en").split("-")[0].lower()
    return lang if lang in SUPPORTED_LANGUAGES else "en"


def t(key: str, hass: HomeAssistant, **kwargs) -> str:
    """A localized string, formatted with the keyword arguments."""
    lang = get_language(hass)
    template = STRINGS.get(key, {}).get(lang) or STRINGS.get(key, {}).get("en") or key
    return template.format(**kwargs) if kwargs else template
