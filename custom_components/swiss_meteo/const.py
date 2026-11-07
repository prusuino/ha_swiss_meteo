"""Constants for the Swiss Meteo integration."""
from __future__ import annotations

DOMAIN = "swiss_meteo"

ATTRIBUTION = "Source: MeteoSwiss (Open Data, CC BY 4.0)"

# Sent with every request. MeteoSwiss serves the files from the federal
# geodata platform; identifying the client helps them attribute traffic.
USER_AGENT = "SwissMeteo/0.1.0 (Home Assistant integration; +https://github.com/prusuino/ha_swiss_meteo)"

# --- Open data endpoints -----------------------------------------------------
DATA_BASE = "https://data.geo.admin.ch"
STAC_BASE = f"{DATA_BASE}/api/stac/v1/collections"
COLLECTION_FORECAST = "ch.meteoschweiz.ogd-local-forecasting"
COLLECTION_STATIONS = "ch.meteoschweiz.ogd-smn"

FORECAST_META_POINTS_URL = f"{DATA_BASE}/{COLLECTION_FORECAST}/ogd-local-forecasting_meta_point.csv"
STATIONS_META_URL = f"{DATA_BASE}/{COLLECTION_STATIONS}/ogd-smn_meta_stations.csv"

# --- Config entry keys -------------------------------------------------------
CONF_POINT_TYPE = "point_type"  # 1 station, 2 postal code centre, 3 mountain point
CONF_POINT_ID = "point_id"
CONF_POINT_NAME = "point_name"
CONF_POINT_LAT = "point_lat"
CONF_POINT_LON = "point_lon"
CONF_POINT_HEIGHT = "point_height"
CONF_STATION = "station"  # SwissMetNet abbreviation, "" for none
CONF_STATION_NAME = "station_name"
CONF_HOURLY = "hourly"  # hourly forecast on/off (the expensive part)
CONF_EXTENDED = "extended"  # uncertainty quantiles, cloud layers, zero-degree level

POINT_TYPE_STATION = 1
POINT_TYPE_POSTAL = 2
POINT_TYPE_MOUNTAIN = 3

# --- Update cadence ----------------------------------------------------------
# A new forecast run appears every hour, a few minutes past the hour; the
# station files are rewritten every ten minutes.
FORECAST_INTERVAL_MINUTES = 60
STATION_INTERVAL_MINUTES = 10

# --- Forecast parameters -----------------------------------------------------
# Daily values of the local forecast (one row per day, nine days). The
# "p" variants count the day in local time; the "d" variants (0-24 UTC)
# exist for weather stations only and are not used.
DAILY_PARAMS = (
    "jp2000d0",  # pictogram number, daytime
    "tre200px",  # max temperature, local day
    "tre200pn",  # min temperature, local day
    "rka150p0",  # precipitation, local day
    "rreq10p0",  # precipitation 10 % quantile
    "rreq90p0",  # precipitation 90 % quantile
)

# Hourly values, the standard set.
HOURLY_PARAMS = (
    "tre200h0",  # air temperature, hourly mean
    "jww003i0",  # icon, weather type of the preceding 3 hours
    "rre150h0",  # precipitation, hourly total
    "rp0003i0",  # probability of precipitation, 3 hours
    "fu3010h0",  # wind speed, hourly mean
    "fu3010h1",  # gust peak, hourly maximum
    "dkl010h0",  # wind direction, hourly mean
    "gre000h0",  # global radiation, hourly mean
    "sre000h0",  # sunshine duration, hourly total
)

# Hourly values added by the "extended" option.
EXTENDED_PARAMS = (
    "treq10h0",  # temperature 10 % quantile
    "treq90h0",  # temperature 90 % quantile
    "rreq10h0",  # precipitation 10 % quantile
    "rreq90h0",  # precipitation 90 % quantile
    "nprolohs",  # low cloud cover
    "npromths",  # medium cloud cover
    "nprohihs",  # high cloud cover
    "zprfr0hs",  # zero-degree level
    "ods000h0",  # diffuse radiation
)

# Files whose rows are grouped by timestamp rather than by point (stable per
# parameter, measured on the published files). Every other file is grouped
# by point, where one block holds all rows of a point.
DATE_MAJOR_PARAMS = frozenset(
    {"tre200h0", "treq10h0", "treq90h0", "zprfr0hs", "tre200dn", "tre200dx", "tre200pn", "tre200px"}
)

# --- Station measurements (10-minute file) -----------------------------------
# column -> (key, unit) of the values exposed as sensors
STATION_PARAMS: dict[str, tuple[str, str]] = {
    "tre200s0": ("temperature", "°C"),
    "tre005s0": ("temperature_5cm", "°C"),
    "tde200s0": ("dew_point", "°C"),
    "ure200s0": ("humidity", "%"),
    "pp0qnhs0": ("pressure_qnh", "hPa"),
    "pp0qffs0": ("pressure_qff", "hPa"),
    "prestas0": ("pressure_station", "hPa"),
    "fu3010z0": ("wind_speed", "km/h"),
    "fu3010z1": ("wind_gust", "km/h"),
    "dkl010z0": ("wind_direction", "°"),
    "rre150z0": ("precipitation", "mm"),
    "sre000z0": ("sunshine", "min"),
    "gre000z0": ("global_radiation", "W/m²"),
    "ods000z0": ("diffuse_radiation", "W/m²"),
    "htoauts0": ("snow_depth", "cm"),
    "xchills0": ("wind_chill", "°C"),
    "tso005s0": ("soil_temperature_5cm", "°C"),
    "tso010s0": ("soil_temperature_10cm", "°C"),
    "tso020s0": ("soil_temperature_20cm", "°C"),
}
