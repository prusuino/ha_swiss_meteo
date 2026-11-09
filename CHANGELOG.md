# Changelog

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
