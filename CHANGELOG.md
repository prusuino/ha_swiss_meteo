# Changelog

## 0.1.0 — 2026-11-07

First release.

- Weather entity for one forecast point (postal-code centre, weather station or mountain point) from the MeteoSwiss local forecast: nine-day daily forecast with high, low, precipitation and its 10–90 % range, chance of rain, wind and gusts; hourly forecast for the coming 200+ hours with temperature and its range, precipitation and its range, chance of rain, wind, gusts, bearing, cloud cover, global radiation, sunshine, zero-degree level and the symbol code. Condition from the MeteoSwiss symbol, day/night aware.
- Current values from a SwissMetNet station (10-minute file): temperature, dew point, humidity, pressure, wind, gusts, direction, precipitation, sunshine, radiation, and more as disabled sensors.
- Today's and tomorrow's high, low and precipitation as sensors; diagnostics for the forecast run, the station time and the data traffic.
- The forecast files (30–34 MB each) are read with HTTP range requests — about 40 KB per parameter where the rows are grouped by point, about 1.7 MB for the temperature file where they are grouped by hour — so the hourly forecast costs about 2 MB per run.
- Setup from a location: the nearest forecast points and stations are offered with their distance. Options: hourly forecast, extended values, station.
- Dashboard card `custom:swiss-meteo-card` with Meteocons icons: current conditions, hourly chart with the uncertainty bands, nine-day strip; visual editor.
- The main card in the Swiss Meteo palette by default (`theme: meteo`, or `ha`). Four cards in the look of the MeteoSwiss website: `custom:swiss-meteo-forecast-card` (the drop-in for the `weather-forecast` card, daily or hourly), `custom:swiss-meteo-daily-card` (nine-day list with low/high boxes, precipitation range, wind and sunshine toggles; Swiss Meteo or Home Assistant palette) and `custom:swiss-meteo-map-card` (Switzerland with a forecast pill per configured place; outline from Natural Earth). `custom:swiss-meteo-sky-card`: the banner look — glass panel on the blue sky, days or hours. The forecast and sky cards take a `size` (normal, large, xl); every card takes `animated: false` for still icons.
- The weather entity carries the point's name, coordinates and elevation as attributes; the daily forecast carries the sunshine hours.
- Derived sensors: daily mean temperature, heating degree days (SIA 381/3, 12/20), global radiation and sunshine sums for today and tomorrow, precipitation of the next 24 hours, next rain. Binary sensors "Rain expected" (next six hours) and "Frost tonight".
- Automation editor entries: triggers "Rain expected", "Rain no longer expected", "Frost expected tonight", "New forecast run" (Home Assistant 2026.10+), conditions "Rain is expected", "No rain is expected", "Frost is expected tonight" (2026.11+). Blueprints "Rain is coming" and "Frost tonight".
- Action `swiss_meteo.import_history`: the station's archive (hourly since 1980, daily since the station's start) into the long-term statistics — mean/min/max of the station sensors, totals of precipitation, sunshine, evaporation and heating degree days as separate statistics.
- Pollen: the hourly concentrations of birch, grasses, alder, hazel, beech, ash and oak from the chosen MeteoSwiss pollen station, with the day's mean and the MeteoSwiss load classes; an overall load-class sensor, shown as a chip on the main card.
- Brand icon and logo.
- German, English, French and Italian.
