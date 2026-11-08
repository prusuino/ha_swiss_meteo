# Security Policy

## Supported Versions

Only the latest release is supported. Please update to the latest version before reporting an issue.

## Reporting a Vulnerability

This integration only reads public files from one Swiss federal data service and the public MeteoAlarm warning feed over HTTPS. It has no credentials, no write access to any external system and no third-party dependencies.

**What it sends:** every request goes to `https://data.geo.admin.ch` (the federal geodata platform that hosts the MeteoSwiss open data) over TLS: HEAD and range (`Range: bytes=…`) requests for the forecast files of the model run (and, when the HEAD probe finds no run, one GET of the collection's STAC item list), GET requests for the station's 10-minute file, the pollen station's hourly file and (with the radar nowcast on) the newest 29 KB radar composite every five minutes, the station's archive files (up to 7 MB each) when you run the history-import action, and — at setup and in the Configure dialog — the lists of forecast points, weather stations and pollen stations. The URLs carry the run time, the parameter name and the station abbreviations. With official warnings on, one GET every ten minutes fetches `https://feeds.meteoalarm.org/api/v1/warnings/feeds-switzerland` (EUMETNET's public CAP feed for the whole country, no parameters). **Your coordinates never leave your instance:** the nearest point and station are chosen locally from the downloaded lists, the forecast is read by the point's id, and the warnings are matched to the point locally against the polygons in the feed. No account, cookie or key is involved; the user agent names this integration.

**What it stores:** the chosen point, weather station and pollen station, their names and coordinates, and the options, in Home Assistant's config entries; the history import writes statistics into the recorder database. The diagnostics download redacts the coordinates, the point's name and the entry's title and unique id.

**Parsing:** the files are CSV; only the rows of the configured point are read, split on `;` and converted to numbers. The warning feed is JSON; its texts are shown as attributes and in the cards as text (escaped), never rendered as HTML. Nothing from a file is executed, rendered as HTML or written to disk. The bundled dashboard card escapes every value it prints.

If you believe you have found a security issue, please report it privately via [GitHub Security Advisories](../../security/advisories/new) rather than opening a public issue. For anything else, please use the regular [Issues](../../issues) tab.
