# Changelog

## 1.9.0 — 2026-11-24

- **New card: Switzerland.** The whole country on the swisstopo relief with layers to switch between: the forecast of 19 places for nine days, every official warning in force or announced as a coloured area with its details on a tap, and the radar of the last hour as a loop. No extra entries are needed for the places. Zoom with the buttons, two fingers or Ctrl and the mouse wheel; the card fits on one screen. Add it as *Swiss Meteo – Switzerland* (`custom:swiss-meteo-switzerland-card`).
- **Avalanches, alerts, forest fire, flood and drought on the same card.** More layers appear by themselves when the integration behind them is set up: the avalanche danger of every region with [Swiss Avalanche Bulletin](https://github.com/prusuino/ha_swiss_avalanche_bulletin), and the alerts of the authorities as points with [Swiss Public Alerts](https://github.com/prusuino/ha_swiss_public_alerts), and from its version 1.9.0 on also the danger of forest fire, flood and drought of every region. Nothing is read twice: the card shows what those integrations already hold. Without them the card has its three layers.
- **New card: climate stripes.** One stripe per year since your station started, blue for colder and red for warmer years than the reference mean (1961–1990 where the station covers it); tap a stripe for the year and its mean. Below it the running month against its normal. Add it as *Swiss Meteo – climate* (`custom:swiss-meteo-climate-card`).
- **Your station's climate.** Nine new sensors from the station's archive: the normal temperature of the day (1991–2020), yesterday's mean and how far it was from normal, the record high and low of the calendar day with their years, the dates of the season's first frost and first snow, and the running month's temperature and precipitation against the normal. The archive is read once (about 1.7 MB) and kept as a small table.
- **Everyday sensors.** Four new yes/no sensors from the hourly forecast: *Laundry Weather* (four dry hours in a row today), *Frozen Windscreen Tomorrow Morning* (1 °C or below between 04:00 and 08:00), *Cool Night After Hot Day* and *Watering Needed*. Each shows its thresholds and figures as attributes.
- **Feels like and pressure trend.** Two new station sensors: the apparent temperature for the whole year (Steadman), and the change of the pressure over three hours with its tendency.
- The Switzerland card reads only while it is open: about 0.65 MB for the forecast at most every three hours, the radar frames of the last hour for the radar layer, nothing extra for the warnings. It all counts in the traffic sensor.
- After the update reload the browser once so that the new card file is used.

## 1.8.4 — 2026-11-24

- **Diagnostics without values.** The diagnostics download no longer contains measured or forecast values, only whether each parameter was read and when. MeteoSwiss publishes the same figures for every station and forecast point, so a few values with their timestamp could name the station or the place although its name and coordinates were redacted. The distance to the nearest rain and the time until it arrives are left out as well. If you posted a diagnostics file publicly, consider removing it.

## 1.8.3 — 2026-11-23

- **Fixed: the triggers stayed silent for what began during an outage.** While MeteoSwiss cannot be reached the entities are unavailable, and Home Assistant ignores every change out of "unavailable". A warning that came into force, rain or frost that became expected, or strong wind that was forecast in that time switched its sensor from unavailable straight to on, and the trigger did not fire. All eleven triggers now compare with the state before the outage: something new fires, something that was already on does not fire a second time, and the "cleared" and "stopped" triggers fire only when the sensor was on before. *New forecast* fires after an outage when the run differs from the one before it.

## 1.8.2 — 2026-11-22

- **The traffic sensor keeps counting over a restart.** "Today" meant since midnight or since the last restart of Home Assistant, whichever was later, so the figure was too low on a day with a restart. The count is now stored with the remembered file positions (written at most every quarter of an hour, and when Home Assistant stops) and continued after a restart; at midnight it starts at zero as before.
- **README:** the snow stations of the SLF (snow depth, new snow, snow temperatures) are part of the sister integration Swiss Avalanche Bulletin; the list of related integrations now says so.

## 1.8.1 — 2026-11-22

- **The warnings no longer cost gigabytes.** The warnings were read from MeteoAlarm's full JSON feed every ten minutes. That feed carries every alert in five languages with its polygon: 21 MB on a day with many warnings, sent uncompressed, about 3 GB a day, and the traffic sensor did not count it. The list of alerts in force is now read from MeteoAlarm's Atom feed (1.7 MB on the same day), only when its length changed and at least once an hour; the few alerts that cover your point are then read in full, once, for the texts and the level. The warnings shown are the same: both ways were compared for twenty places across Switzerland in four languages.
- **The traffic sensor counts every feed.** Until now it showed what the forecast, the radar and a history import transferred. The station, the rain gauge, the pollen station, the warnings and Open-Meteo are counted now as well. It still starts at zero after a restart of Home Assistant.
- **The forecast is read at the place it stood last time.** Until now every model run was searched for from scratch: about 2.5 MB for the hourly forecast and another 7 MB for the extended values, every hour, which is about 230 MB a day with both switched on (the README said "a few megabytes a day"). The integration now remembers where your point stands in each file, also over a restart, and reads the rows of the large files one block at a time with a window of 1 KB instead of 4 to 12 KB. Measured: 0.4 MB per run for the hourly forecast and another 0.8 MB for the extended values, about 30 MB a day with both. The values read are the same; both ways were compared on the live files for four places.
- **Honest figures.** The README and the setup dialog now state what was measured, including 8 to 45 MB a day for the radar. The README also names MeteoAlarm as the one source besides the federal platform that is on by default, and counts six cards and the blueprints correctly.
- **Days say more without the hourly forecast.** With the hourly forecast switched off, a day showed temperature and rain amount only. It now also has the rain probability, wind, gusts and sunshine: four series are read for this, as often as the daily values (well under 2 MB a day).
- **Small files come compressed.** Station, rain gauge and pollen files are requested compressed (a station file is 4 KB instead of 16 KB).
- **Repairs notices for warnings and radar.** A warning feed that cannot be read for an hour, or radar frames that stay away for half an hour, now raise a notice under *Settings → Repairs*, as the forecast, the stations, pollen and Open-Meteo already did. It disappears with the next successful read.
- **Diagnostics without your stations.** The download already left out the coordinates and the place name. The abbreviations and names of the weather, precipitation and pollen stations and the altitude of the forecast point are redacted now too, since they give the area away just as well.
- **Fixed: radar and history import with files that do not exist yet.** The open-data host answers 403, not 404, for a file that does not exist. The radar took that for a failure instead of reading the frame before the newest one (after a restart its entities could stay unavailable for five minutes), and a history import stopped at a decade for which the station has no file.
- **Fixed: a slow server during a history import.** A request that timed out while importing the station history ended the action with an unexpected error instead of the translated "could not be read" message.
- **For contributors:** a lint workflow (ruff) and a weekly smoke test that reads every source once with the integration's own readers (`scripts/smoke_test.py`), so that a change at MeteoSwiss, MeteoAlarm or Open-Meteo is noticed before a user reports it.

## 1.8.0 — 2026-11-21

- **Quality scale: Gold.** Entity names, icons and error messages now come from Home Assistant's translation files instead of the integration's own code, in German, English, French and Italian. Entity ids, unique ids and history stay as they are, and the names read as before.
- **Icons come from the icon file.** They look as before, and the warning level still shows the outlined icon while no warning is in force. The entities no longer carry an `icon` state attribute; a template or card that read it gets nothing now. An icon you set for an entity yourself stays.
- **Translated errors.** When the station history cannot be imported, the error the action shows is translated like the other action errors; the errors of a failed read carry a translation as well.
- **README: troubleshooting.** A new section lists what to check when a sensor is unknown, unavailable or missing.

## 1.7.1 — 2026-11-19

- The Home Assistant Marketplace lists the integration under *Weather & alerts → Forecasts*. The repository is marked as made for Switzerland. Nothing changes in how the integration works.

## 1.7.0 — 2026-11-12

- **New: optional precipitation station.** Besides its weather stations, MeteoSwiss runs about 140 automatic rain gauges at other places, so in some regions a gauge is closer than the next weather station. The setup, Reconfigure and the Configure dialog now offer a fourth choice, **Precipitation station**: with a gauge chosen, the measured precipitation comes from it, while temperature, wind, pressure and all other values still come from the weather station. The precipitation sensor keeps its entity id and names the gauge in its `station` and `station_name` attributes; the weather entity names it as `precipitation_station`.
- **Nothing changes unless you choose one.** Existing entries keep the precipitation of their weather station. In a new setup a gauge is suggested only when it is nearer than the nearest weather station; "–" keeps the weather station's value.
- **Station history follows the choice.** With a precipitation station, *Import station history* builds the precipitation total from the archive of that gauge; an entry with a precipitation station alone can import it too.
- **Repair notice and diagnostics for the new part.** When the gauge could not be read for an hour a notice appears under Settings → Repairs; the diagnostics download lists the state of the precipitation read.
- **Fixed: forecast for points that are not a postal code.** The forecast files list their points in more than one order and the reader knew only one of them. With a forecast point that is a station or a mountain spot, values could be missing — the precipitation amounts most of all — and in the worst case the setup did not finish while requests kept going to the open-data server. The reader now recognises the order of each file, reads a file of daily values whole when a point is listed out of order, and no longer loses the last day of the daily temperatures for the last points of the list. Forecast points that are a postal code were read correctly.
- **One read of a file has a request budget.** Whatever a file looks like, a read ends after a fixed number of requests and the parameter is reported as not read, instead of asking the server again and again.

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
