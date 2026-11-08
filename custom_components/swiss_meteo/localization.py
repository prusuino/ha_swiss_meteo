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
    "surface_temperature": {"de": "Oberflächentemperatur", "en": "Surface Temperature", "fr": "Température de surface", "it": "Temperatura superficiale"},
    "vapour_pressure": {"de": "Dampfdruck", "en": "Vapour Pressure", "fr": "Pression de vapeur", "it": "Pressione di vapore"},
    "wind_gust_3s": {"de": "Böen 3 s", "en": "Wind Gust 3 s", "fr": "Rafales 3 s", "it": "Raffiche 3 s"},
    "geopotential_850": {"de": "Geopotential 850 hPa", "en": "Geopotential Height 850 hPa", "fr": "Géopotentiel 850 hPa", "it": "Geopotenziale 850 hPa"},
    "geopotential_700": {"de": "Geopotential 700 hPa", "en": "Geopotential Height 700 hPa", "fr": "Géopotentiel 700 hPa", "it": "Geopotenziale 700 hPa"},
    "longwave_incoming": {"de": "Langwellenstrahlung einfallend", "en": "Longwave Incoming Radiation", "fr": "Rayonnement infrarouge incident", "it": "Radiazione a onda lunga incidente"},
    "longwave_outgoing": {"de": "Langwellenstrahlung ausgehend", "en": "Longwave Outgoing Radiation", "fr": "Rayonnement infrarouge sortant", "it": "Radiazione a onda lunga uscente"},
    "reflected_radiation": {"de": "Reflektierte Strahlung", "en": "Reflected Shortwave Radiation", "fr": "Rayonnement réfléchi", "it": "Radiazione riflessa"},
    "foehn_index": {"de": "Föhnindex", "en": "Foehn Index", "fr": "Indice de foehn", "it": "Indice di favonio"},
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
    # derived figures
    "today_mean": {"de": "Heute Tagesmittel", "en": "Today Mean Temperature", "fr": "Moyenne aujourd'hui", "it": "Media oggi"},
    "tomorrow_mean": {"de": "Morgen Tagesmittel", "en": "Tomorrow Mean Temperature", "fr": "Moyenne demain", "it": "Media domani"},
    "heating_degree_days_today": {"de": "Heute Heizgradtage", "en": "Today Heating Degree Days", "fr": "Degrés-jours de chauffage aujourd'hui", "it": "Gradi giorno riscaldamento oggi"},
    "heating_degree_days_tomorrow": {"de": "Morgen Heizgradtage", "en": "Tomorrow Heating Degree Days", "fr": "Degrés-jours de chauffage demain", "it": "Gradi giorno riscaldamento domani"},
    "radiation_today": {"de": "Heute Globalstrahlung", "en": "Today Global Radiation", "fr": "Rayonnement global aujourd'hui", "it": "Radiazione globale oggi"},
    "radiation_tomorrow": {"de": "Morgen Globalstrahlung", "en": "Tomorrow Global Radiation", "fr": "Rayonnement global demain", "it": "Radiazione globale domani"},
    "sunshine_today": {"de": "Heute Sonnenschein", "en": "Today Sunshine", "fr": "Ensoleillement aujourd'hui", "it": "Soleggiamento oggi"},
    "sunshine_tomorrow": {"de": "Morgen Sonnenschein", "en": "Tomorrow Sunshine", "fr": "Ensoleillement demain", "it": "Soleggiamento domani"},
    "precipitation_next_24h": {"de": "Niederschlag nächste 24 h", "en": "Precipitation Next 24 h", "fr": "Précipitations 24 h à venir", "it": "Precipitazioni prossime 24 h"},
    "next_rain": {"de": "Nächster Regen", "en": "Next Rain", "fr": "Prochaine pluie", "it": "Prossima pioggia"},
    "rain_expected": {"de": "Regen erwartet", "en": "Rain Expected", "fr": "Pluie attendue", "it": "Pioggia prevista"},
    "frost_tonight": {"de": "Frost heute Nacht", "en": "Frost Tonight", "fr": "Gel cette nuit", "it": "Gelo stanotte"},
    # pollen
    "pollen_birch": {"de": "Pollen Birke", "en": "Pollen Birch", "fr": "Pollen bouleau", "it": "Polline betulla"},
    "pollen_grasses": {"de": "Pollen Gräser", "en": "Pollen Grasses", "fr": "Pollen graminées", "it": "Polline graminacee"},
    "pollen_alder": {"de": "Pollen Erle", "en": "Pollen Alder", "fr": "Pollen aulne", "it": "Polline ontano"},
    "pollen_hazel": {"de": "Pollen Hasel", "en": "Pollen Hazel", "fr": "Pollen noisetier", "it": "Polline nocciolo"},
    "pollen_beech": {"de": "Pollen Buche", "en": "Pollen Beech", "fr": "Pollen hêtre", "it": "Polline faggio"},
    "pollen_ash": {"de": "Pollen Esche", "en": "Pollen Ash", "fr": "Pollen frêne", "it": "Polline frassino"},
    "pollen_oak": {"de": "Pollen Eiche", "en": "Pollen Oak", "fr": "Pollen chêne", "it": "Polline quercia"},
    "pollen_level": {"de": "Pollenbelastung", "en": "Pollen Load", "fr": "Charge pollinique", "it": "Carico pollinico"},
    "warning_level": {"de": "Warnstufe", "en": "Warning Level", "fr": "Niveau d'alerte", "it": "Livello di allerta"},
    "warning_active": {"de": "Warnung aktiv", "en": "Warning Active", "fr": "Alerte en cours", "it": "Allerta in corso"},
    "radar_rain_rate": {"de": "Radar Regenrate", "en": "Radar Rain Rate", "fr": "Radar intensité de pluie", "it": "Radar intensità di pioggia"},
    "radar_rain_distance": {"de": "Radar nächster Regen", "en": "Radar Nearest Rain", "fr": "Radar pluie la plus proche", "it": "Radar pioggia più vicina"},
    "radar_rain_eta": {"de": "Radar Regen in", "en": "Radar Rain In", "fr": "Radar pluie dans", "it": "Radar pioggia tra"},
    "raining": {"de": "Es regnet", "en": "Raining", "fr": "Il pleut", "it": "Piove"},
    "strong_wind_expected": {"de": "Starkwind erwartet", "en": "Strong Wind Expected", "fr": "Vent fort attendu", "it": "Vento forte previsto"},
    "rain_approaching": {"de": "Regen zieht auf", "en": "Rain Approaching", "fr": "Pluie en approche", "it": "Pioggia in arrivo"},
    "model_pollen": {"de": "{station}, Pollen {pollen}", "en": "{station}, pollen {pollen}", "fr": "{station}, pollen {pollen}", "it": "{station}, pollini {pollen}"},
}


def get_language(hass: HomeAssistant) -> str:
    lang = (hass.config.language or "en").split("-")[0].lower()
    return lang if lang in SUPPORTED_LANGUAGES else "en"


def t(key: str, hass: HomeAssistant, **kwargs) -> str:
    """A localized string, formatted with the keyword arguments."""
    lang = get_language(hass)
    template = STRINGS.get(key, {}).get(lang) or STRINGS.get(key, {}).get("en") or key
    return template.format(**kwargs) if kwargs else template
