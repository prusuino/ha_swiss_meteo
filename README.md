# Swiss Meteo for Home Assistant

A Home Assistant custom integration for the **MeteoSwiss** forecast and measurements, from the official open data: the local forecast of your postal code (nine days, hour by hour, with the uncertainty range), the live values of the nearest SwissMetNet station every ten minutes, and a dashboard card with animated icons — read so sparingly that the hourly forecast costs a few megabytes a day, not hundreds.

> **Open data only.** Everything comes from the files MeteoSwiss publishes under CC BY 4.0 on the federal geodata platform. No app backend, no scraping, no API key, no third-party service, no Python dependencies.

## Background

Since 2025 MeteoSwiss publishes its data openly: the local forecast for every Swiss postal code, the automatic station network, radar, pollen. The forecast, though, comes as one file per parameter and model run covering all of Switzerland — 30 to 34 MB for an hourly value, every hour. Reading your place out of that without pulling the whole file is what this integration does differently: the rows of one forecast point are fetched with HTTP range requests — a binary search over the file where the rows are grouped by point, a predicted position where they are grouped by hour — so a parameter costs some 40 KB instead of 33 MB. The traffic is shown as a sensor, so you can see it stay small.

## What it provides

| Entity | Description |
|---|---|
| `weather.swiss_meteo_<id>` | The weather entity. Condition from the MeteoSwiss symbol (day/night aware), temperature, humidity, dew point, pressure, wind, gusts and bearing from the station when one is configured (else from the forecast). **Daily forecast** for nine days: condition, high, low, precipitation and its 10–90 % range, chance of rain, wind and gusts. **Hourly forecast** (option, on by default) for the coming 200+ hours: temperature with its 10–90 % range, precipitation with its range, chance of rain, wind, gusts, bearing, cloud cover, global radiation, sunshine minutes, zero-degree level and the symbol code. Attributes: `forecast_run`, `symbol`, `symbol_meaning`, `precipitation_probability`, `zero_degree_level`, `station`, `station_time`, and the point's `point_name`, `latitude`, `longitude` and `elevation` (so the entity can be placed on a map). |
| `sensor.swiss_meteo_<id>_temperature` … | The station's 10-minute values: temperature, dew point, humidity, pressure (QNH), wind, gusts, wind direction, precipitation, sunshine, global radiation enabled by default; temperature at 5 cm, pressure QFF and station level, diffuse radiation, snow depth, wind chill and soil temperatures at 5/10/20 cm created disabled. Unavailable once the station's file is older than 45 minutes. |
| `sensor.swiss_meteo_<id>_today_max` / `_today_min` / `_today_precipitation` | Today's high, low and precipitation from the daily forecast; the same for tomorrow (`_tomorrow_…`). |
| `sensor.swiss_meteo_<id>_today_mean` / `_tomorrow_mean` | The day's mean temperature: the mean of the hourly values when the day is covered, else of the high and low. |
| `sensor.swiss_meteo_<id>_heating_degree_days_today` / `_tomorrow` | Heating degree days after SIA 381/3 (12/20): 20 °C minus the mean on days with a mean below 12 °C, else 0. For heating and heat-pump automations. |
| `sensor.swiss_meteo_<id>_radiation_today` / `_tomorrow` | Global radiation sum of the day in kWh/m², from the hourly forecast — tomorrow's figure is the one for PV planning; today's covers the hours still in the run. |
| `sensor.swiss_meteo_<id>_sunshine_today` / `_tomorrow` | Sunshine hours of the day. |
| `sensor.swiss_meteo_<id>_precipitation_next_24h` | Precipitation of the coming 24 hours. |
| `sensor.swiss_meteo_<id>_next_rain` | The first coming hour with rain (0.1 mm or more), as a timestamp, with the amount and the hours until then as attributes. |
| `binary_sensor.swiss_meteo_<id>_rain_expected` | On when rain is forecast for one of the next six hours. Attributes: next rain, amount in 6 and 24 hours. |
| `binary_sensor.swiss_meteo_<id>_frost_tonight` | On when the forecast drops to 0 °C or below before 09:00 the next morning, with the minimum and its hour. |
| `sensor.swiss_meteo_<id>_forecast_run` | When the forecast run in use was issued (diagnostic), with the parameters read and any that were missing. |
| `sensor.swiss_meteo_<id>_station_time` | Time of the newest station row (diagnostic). |
| `sensor.swiss_meteo_<id>_traffic_today` | Megabytes read from MeteoSwiss since midnight (diagnostic), with the request count. |

`<id>` is a short per-entry code so that two places do not collide; names are translated (German, English, French, Italian), ids are not.

Data updates: a new forecast run is looked for every 15 minutes with a single HEAD request and read when it appears (hourly values with every run, daily values at most every three hours); the station file is read every ten minutes. Everything is read from `data.geo.admin.ch` over TLS.

## Automations

### Triggers and conditions in the automation editor

On Home Assistant 2026.10 or newer the integration adds its own entries to the automation editor, so you do not need a state trigger on a specific entity:

| Trigger | Fires when |
|---|---|
| **Rain expected** | rain is forecast for one of the next six hours |
| **Rain no longer expected** | the six-hour window is dry again |
| **Frost expected tonight** | the forecast drops to 0 °C or below before the next morning |
| **New forecast run** | a new MeteoSwiss run has been read (hourly) |

On 2026.11 or newer there are also the conditions **Rain is expected**, **No rain is expected** and **Frost is expected tonight**. Each trigger and condition targets the integration's own entities (pick an entity, a device or an area); the usual *for* duration and *trigger when* / *condition passes if* options apply.

```yaml
triggers:
  - trigger: swiss_meteo.rain_expected
    target:
      entity_id: binary_sensor.swiss_meteo_ab12_rain_expected
conditions:
  - condition: swiss_meteo.is_dry
    target:
      entity_id: binary_sensor.swiss_meteo_ab12_rain_expected
```

On older versions use a state trigger on the binary sensors; they carry the same information.

### Blueprints

Two blueprints with an import button:

**Rain is coming** — a notification when rain is expected within six hours (when and how much), plus your own actions when rain is expected and when it is over (close the awning, skip the irrigation). Quiet hours for the notification.

[![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fprusuino%2Fha_swiss_meteo%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Frain_expected_notification.yaml)

**Frost tonight** — an evening notification when frost is expected before the morning (the minimum and its hour), plus your own actions.

[![Import blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fprusuino%2Fha_swiss_meteo%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ffrost_tonight_notification.yaml)

### Energy

The heating degree days and the mean temperature feed heating and heat-pump automations (lower the flow temperature on a mild day, pre-heat before a cold one); tomorrow's global radiation and sunshine hours tell a PV household what to expect, hour by hour via the hourly forecast's `global_radiation` (W/m²) and `sunshine_minutes`.

## Dashboard card

The integration ships a Lovelace card, **Swiss Meteo** (`custom:swiss-meteo-card`), with a visual editor: the current conditions with a large animated icon and the station values, an hourly chart — temperature line with its uncertainty band, precipitation bars with their 10–90 % range (the chance of rain sets their opacity), the symbols along the top, day boundaries — and the nine-day strip with high, low, precipitation, chance and range. The icons are [Meteocons](https://meteocons.com) by Bas Milius (MIT), bundled with the integration; the MeteoSwiss pictures themselves are proprietary and not used.

The card file is served by the integration, but registering it as a Lovelace resource is left to you — the resource list is part of your dashboard configuration. It is a one-time step:

**Settings → Dashboards → ⋮ (top right) → Resources → + Add resource**

| | |
|---|---|
| URL | `/swiss_meteo_files/swiss-meteo-card.js` |
| Resource type | JavaScript module |

Then reload the page (Ctrl/Cmd+Shift+R). The *Resources* entry is only shown when **Advanced mode** is enabled in your user profile. Afterwards the card appears in the card picker as **Swiss Meteo**:

```yaml
type: custom:swiss-meteo-card
entity: weather.swiss_meteo_ab12
hours: 24        # 12–72 hours in the chart
days: 9          # 1–9 days in the strip
show_current: true
show_hourly: true
show_daily: true
```

The main card uses the dark blue MeteoSwiss palette by default (`theme: meteo`); `theme: ha` follows your Home Assistant theme instead. Three more cards come with the same file, in the look of the MeteoSwiss website:

**Swiss Meteo – forecast** (`custom:swiss-meteo-forecast-card`): the drop-in for Home Assistant's `weather-forecast` card with the same options — current conditions on top and a row of days (symbol, low and high, precipitation) or hours (symbol, temperature, precipitation or chance of rain).

```yaml
type: custom:swiss-meteo-forecast-card
entity: weather.swiss_meteo_ab12
forecast_type: daily   # or hourly
show_current: true
show_forecast: true
columns: 0             # 0 = automatic (7 days / 8 hours)
theme: meteo
```


**Swiss Meteo – daily list** (`custom:swiss-meteo-daily-card`): the nine-day list — weekday, symbol, low and high in boxes, precipitation with its 10–90 % range — with the *Wind* and *Sunshine* toggles that add the day's wind, gusts and sunshine hours to each row. `theme: meteo` (default) uses the dark blue MeteoSwiss palette, `theme: ha` your Home Assistant theme.

```yaml
type: custom:swiss-meteo-daily-card
entity: weather.swiss_meteo_ab12
days: 8
show_wind: false
show_sunshine: false
show_toggles: true
theme: meteo
```

**Swiss Meteo – map** (`custom:swiss-meteo-map-card`): Switzerland with a forecast pill for every configured place — symbol, name, low and high of the chosen day (`day: 0` today, `1` tomorrow, …). Add the integration once per place you want on the map; without `entities` every Swiss Meteo weather entity is shown. The outline and the lakes come from [Natural Earth](https://www.naturalearthdata.com) (public domain).

```yaml
type: custom:swiss-meteo-map-card
day: 0
show_names: true
# entities: [weather.swiss_meteo_ab12, weather.swiss_meteo_cd34]
```

The standard `weather-forecast` card and the weather tile features work with the entity as well.

## Installation

### Home Assistant Marketplace / HACS

Add `https://github.com/prusuino/ha_swiss_meteo` as a custom repository (category *Integration*), install **Swiss Meteo**, restart Home Assistant.

### Manual

Copy `custom_components/swiss_meteo` into your `custom_components` directory and restart.

## Setup

1. **Settings → Devices & Services → Add Integration → Swiss Meteo.**
2. Confirm or move the **location** (your Home Assistant location is pre-filled), and choose whether you want the **hourly forecast** (about 2 MB per model run, every hour) and the **extended hourly values** (temperature and precipitation uncertainty range, cloud layers, zero-degree level — about twice that).
3. Pick the **forecast point** — the five nearest are listed with their distance: postal-code centres, weather stations and mountain points (summits, passes, resorts) — and the **weather station** for the live values among the four nearest. Altitude and exposure matter more than distance: a station on a nearby hill is not your valley. Without a station the current values come from the forecast.
4. Done. The **Configure** dialog switches the hourly forecast and the extended values on or off and lets you pick another station (the eight nearest are listed); a change reloads the entry, entity ids and history are kept.

Each entry is one place; add the integration again for another postal code or a summit.

## Notes

- The forecast is the one shown in the MeteoSwiss app and on its website for the postal code, updated every hour; the symbol codes (1–42 by day, 101–142 by night) are mapped to Home Assistant conditions and, in the card, to Meteocons.
- Daily highs, lows and precipitation count the local calendar day; the daily entries also carry the day's maximum wind and gusts, the chance of rain and the sunshine hours. The hourly list starts with the current hour; past hours of the run are dropped.
- MeteoSwiss has announced a point API for the local forecast (beta by the end of 2026). The file reader is built behind an interface so the integration can switch to it when it is there — entities and ids will not change.
- **Weather warnings** are not part of the MeteoSwiss open data. Home Assistant's `meteoalarm` integration carries the official warnings at region level; a warning entity for this integration is on the list.
- **Download diagnostics** (entry menu) gives the entry's configuration (coordinates redacted), the parameters read, the newest values and the traffic figures.

## Disclaimer

This is an independent project and is not affiliated with, endorsed by or supported by the Federal Office of Meteorology and Climatology MeteoSwiss. Data: MeteoSwiss, CC BY 4.0. The forecast and the measurements are provided as published; the author gives no warranty for their correctness, completeness or availability. Do not rely on this integration for safety-relevant decisions — MeteoSwiss's own warnings and channels remain the authoritative source.

## License

MIT — see [LICENSE](LICENSE). Third-party notices in [NOTICE.md](NOTICE.md).

## Related integrations

Part of a series of Home Assistant integrations for Switzerland by the same author: [Swiss Hail Protection](https://github.com/prusuino/ha_swiss_hail_protection), [Swiss Public Alerts](https://github.com/prusuino/ha_swiss_public_alerts), [Swiss Waters](https://github.com/prusuino/ha_swiss_waters), [Swiss Avalanche Bulletin](https://github.com/prusuino/ha_swiss_avalanche_bulletin), [Swiss Earthquakes](https://github.com/prusuino/ha_swiss_earthquakes), [Swiss Transport](https://github.com/prusuino/ha_swiss_transport), [Swiss Electricity Price](https://github.com/prusuino/ha_swiss_electricity_price), [Swiss Solar Reference Price](https://github.com/prusuino/ha_swiss_solar_reference_price), [Swiss Charging Stations](https://github.com/prusuino/ha_swiss_charging_stations), [Swiss Lottery](https://github.com/prusuino/ha_swiss_lottery).

## Support

Questions and bug reports: [Issues](../../issues). Please attach the diagnostics download to a bug report.
