# Changelog

## 1.6.0 — 2026-11-11

- **New: optional air quality, UV index and pollen forecast from Open-Meteo.** MeteoSwiss publishes none of the three as open data for a point. A new switch in the setup and in the Configure dialog — **off by default** — adds them from the free Open-Meteo air quality API: the European Air Quality Index with its band in words, PM10, PM2.5, nitrogen dioxide, ozone, the UV index with today's maximum, and a four-day pollen forecast for alder, birch, grass, mugwort, olive and ragweed. The values are modelled (Copernicus CAMS, about 11 km), not measured and **not official MeteoSwiss data**; they sit on a device of their own and every sensor says so in its attribution. The measured MeteoSwiss pollen sensors are unchanged.
- **What the option sends.** One request an hour to Open-Meteo with the coordinates of the forecast point, rounded to two decimals. With the switch off, no request leaves for Open-Meteo. Switching it off again removes the device and its sensors.
- **Repair notice and diagnostics for the new part.** When Open-Meteo could not be read for six hours in a row a notice appears under Settings → Repairs; the diagnostics download lists the state of the Open-Meteo read.
- **Parallel updates declared.** All entity platforms set `PARALLEL_UPDATES = 0` (the coordinators do the reading), which closes the *parallel-updates* rule of the quality scale.
- **User-Agent follows the release.** The version in the request header is read from the manifest instead of being a fixed string.
- **Fixed: tomorrow's mean temperature showed today's.** `sensor.swiss_meteo_<id>_tomorrow_mean` and its `hours_in_forecast` attribute were worked out for the running day. They now cover tomorrow.
- **Silver on the quality scale.** The tests now cover 99 % of the integration — forecast, station, pollen, warnings, radar, history import, every entity platform, the actions, triggers and conditions, the config and options flow — and answer from memory, without network access. That closes the *test-coverage* rule, the last one open for Silver; the manifest declares **silver** and the test workflow fails when the coverage drops below 95 %.

## 1.5.4 — 2026-11-09

- **Listed in the Marketplace default catalog.** The README now leads with the Marketplace/HACS search and keeps the custom-repository steps as a fallback, as suggested by @frenck in the HACS review (hacs/default #13678).

## 1.5.3 — 2026-11-09

- **Card hardening.** Condition and basemap lookups match own table keys only, so an unexpected state or option can no longer break the card. Follow-up to the HACS review of Swiss Lottery by @frenck.

## 1.5.2 — 2026-11-09

- **Version on the service card.** The integration's version now appears on its service card under Settings → Devices & services, where the entities are listed.

## 1.5.1 — 2026-11-08

- **Maintenance.** The integration now keeps its per-entry data in the config entry's runtime data, as the Home Assistant quality scale asks, and declares the **bronze** tier in its manifest. The README gained a removal section. A test suite (parsers, forecast helpers, config flow) runs on every push. No change to entities or configuration.

## 1.5.0 — 2026-11-08

- **New: repair notices.** A notice under **Settings → Repairs** when the forecast could not be read for three refreshes in a row, when the weather station's values could not be read for an hour (the station may have been discontinued: pick another in *Configure*), and when the pollen station's values could not be read. Each clears itself with the next successful read. In all four languages.
- **New: reconfigure an entry in place.** The entry's menu under **Settings → Devices & services** now offers *Reconfigure*: move the marker or search for another place or postal code, then pick the forecast point, the weather station and the pollen station around it, as in the setup. The entry keeps its entities, their ids and history; the title follows the new point. The hourly forecast, extended values, warnings and radar switches stay as set in *Configure*. A change to a point another entry already uses is refused.

## 1.4.0 — 2026-11-08

- Radar nowcast from the MeteoSwiss precipitation composite (PRECIP, every 5 minutes, 29 KB per frame, read without an HDF5 library): rain rate at the point, distance to the nearest rain, estimated minutes until rain arrives from the motion of the rain field; binary sensors "Raining" and "Rain approaching"; triggers "Rain approaching", "Rain started", "Rain stopped"; conditions "It is raining", "It is not raining", "Rain is approaching"; radar chip on the main card; option to switch the radar off.
- Radar card `custom:swiss-meteo-radar-card`: the last two hours of radar frames around the place as a loop, plus up to an hour extrapolated along the measured motion (estimate), on the swisstopo national map (grey or colour, or none with the Swiss border and lakes drawn instead), distance rings, marker, zoom from 200 km down to 25 km, play/pause and slider. Image entity `image.<id>_radar` with the newest frame. The integration keeps two hours of 200 × 200 km crops and renders the PNGs itself.
- "Strong wind expected" binary sensor with a gust threshold (Configure dialog, 60 km/h by default), triggers "Strong wind expected" / "no longer expected" and condition "Strong wind is expected".
- Action `swiss_meteo.best_window`: the driest, sunniest or calmest window of a given length within the coming hours, with a response.
- Blueprints "Strong wind: raise the blinds", "Laundry window" and "Pause the irrigation when rain is coming".

## 1.3.1 — 2026-11-08

- README: screenshots of every card (main card in the three colour schemes, forecast, daily list, map, sky, compact sizes).
- Place search: when the typed postal code has no forecast point (3000 Bern, 8000 Zürich), the nearest postal codes of the area are offered; places are listed before stations.

## 1.3.0 — 2026-11-08

First public release.

- Weather entity for one forecast point (postal-code centre, weather station or mountain point) from the MeteoSwiss local forecast: nine-day daily forecast with high, low, precipitation and its 10–90 % range, chance of rain, wind and gusts; hourly forecast for the coming 200+ hours with temperature and its range, precipitation and its range, chance of rain, wind, gusts, bearing, cloud cover, global radiation, sunshine, zero-degree level and the symbol code. Condition from the MeteoSwiss symbol, day/night aware.
- Current values from a SwissMetNet station (10-minute file): temperature, dew point, humidity, pressure, wind, gusts, direction, precipitation, sunshine, radiation, and more as disabled sensors.
- Today's and tomorrow's high, low and precipitation as sensors; diagnostics for the forecast run, the station time and the data traffic.
- The forecast files (30–34 MB each) are read with HTTP range requests — about 40 KB per parameter where the rows are grouped by point, about 1.7 MB for the temperature file where they are grouped by hour — so the hourly forecast costs about 2 MB per run.
- Setup from a location: the nearest forecast points and stations are offered with their distance. Options: hourly forecast, extended values, station.
- Dashboard card `custom:swiss-meteo-card` with Meteocons icons: current conditions, hourly chart with the uncertainty bands, nine-day strip; visual editor.
- The main card in the Swiss Meteo palette by default (`theme: meteo`, or `ha`). Four cards in the look of the MeteoSwiss website: `custom:swiss-meteo-forecast-card` (the drop-in for the `weather-forecast` card, daily or hourly), `custom:swiss-meteo-daily-card` (nine-day list with low/high boxes, precipitation range, wind and sunshine toggles; Swiss Meteo or Home Assistant palette) and `custom:swiss-meteo-map-card` (Switzerland with a forecast pill per configured place; outline from Natural Earth). `custom:swiss-meteo-sky-card`: the banner look — glass panel on the blue sky, days or hours. The main, forecast and sky cards take a `size` (small, normal, large, xl); every card takes `theme` (Swiss Meteo palette, Home Assistant theme, or the deep-blue glass look) and `animated: false` for still icons.
- The weather entity carries the point's name, coordinates and elevation as attributes; the daily forecast carries the sunshine hours.
- Derived sensors: daily mean temperature, heating degree days (SIA 381/3, 12/20), global radiation and sunshine sums for today and tomorrow, precipitation of the next 24 hours, next rain. Binary sensors "Rain expected" (next six hours) and "Frost tonight".
- Automation editor entries: triggers "Rain expected", "Rain no longer expected", "Frost expected tonight", "New forecast run" (Home Assistant 2026.10+), conditions "Rain is expected", "No rain is expected", "Frost is expected tonight" (2026.11+). Blueprints "Rain is coming" and "Frost tonight".
- Action `swiss_meteo.import_history`: the station's archive (hourly since 1980, daily since the station's start) into the long-term statistics — mean/min/max of the station sensors, totals of precipitation, sunshine, evaporation and heating degree days as separate statistics.
- Official warnings (MeteoSwiss via MeteoAlarm): warning-level sensor (none, yellow, orange, red) with the warnings in force and announced as attributes, "Warning active" binary sensor, triggers "Warning issued" / "Warning cleared", condition "A warning is in force", warning banners on the main, forecast and sky cards. The alerts' polygons are matched to the forecast point locally.
- Setup by place name or postal code as an alternative to the map marker.
- Pollen: the hourly concentrations of birch, grasses, alder, hazel, beech, ash and oak from the chosen MeteoSwiss pollen station, with the day's mean and the MeteoSwiss load classes; an overall load-class sensor, shown as a chip on the main card.
- Brand icon and logo.
- German, English, French and Italian.
