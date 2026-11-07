# Changelog

## 0.1.0 — 2026-11-07

First release.

- Weather entity for one forecast point (postal-code centre, weather station or mountain point) from the MeteoSwiss local forecast: nine-day daily forecast with high, low, precipitation and its 10–90 % range, chance of rain, wind and gusts; hourly forecast for the coming 200+ hours with temperature and its range, precipitation and its range, chance of rain, wind, gusts, bearing, cloud cover, global radiation, sunshine, zero-degree level and the symbol code. Condition from the MeteoSwiss symbol, day/night aware.
- Current values from a SwissMetNet station (10-minute file): temperature, dew point, humidity, pressure, wind, gusts, direction, precipitation, sunshine, radiation, and more as disabled sensors.
- Today's and tomorrow's high, low and precipitation as sensors; diagnostics for the forecast run, the station time and the data traffic.
- The forecast files (30–34 MB each) are read with HTTP range requests — about 40 KB per parameter where the rows are grouped by point, about 1.7 MB for the temperature file where they are grouped by hour — so the hourly forecast costs about 2 MB per run.
- Setup from a location: the nearest forecast points and stations are offered with their distance. Options: hourly forecast, extended values, station.
- Dashboard card `custom:swiss-meteo-card` with Meteocons icons: current conditions, hourly chart with the uncertainty bands, nine-day strip; visual editor.
- Two cards in the look of the MeteoSwiss website: `custom:swiss-meteo-daily-card` (nine-day list with low/high boxes, precipitation range, wind and sunshine toggles; MeteoSwiss or Home Assistant palette) and `custom:swiss-meteo-map-card` (Switzerland with a forecast pill per configured place; outline from Natural Earth).
- The weather entity carries the point's name, coordinates and elevation as attributes; the daily forecast carries the sunshine hours.
- German, English, French and Italian.
