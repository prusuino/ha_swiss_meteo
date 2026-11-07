# Security Policy

## Supported Versions

Only the latest release is supported. Please update to the latest version before reporting an issue.

## Reporting a Vulnerability

This integration only reads public files from one Swiss federal data service over HTTPS. It has no credentials, no write access to any external system and no third-party dependencies.

**What it sends:** every request goes to `https://data.geo.admin.ch` (the federal geodata platform that hosts the MeteoSwiss open data) over TLS: HEAD and range (`Range: bytes=…`) requests for the forecast files of the model run, GET requests for the station's 10-minute file, and — at setup and in the Configure dialog — the lists of forecast points and stations. The URLs carry the run time, the parameter name and the station abbreviation. **Your coordinates never leave your instance:** the nearest point and station are chosen locally from the downloaded lists, and the forecast is read by the point's id. No account, cookie or key is involved; the user agent names this integration.

**What it stores:** the chosen point and station, their names and coordinates, and the two options, in Home Assistant's config entries. The diagnostics download redacts the coordinates and the entry's title and unique id.

**Parsing:** the files are CSV; only the rows of the configured point are read, split on `;` and converted to numbers. Nothing from a file is executed, rendered as HTML or written to disk. The bundled dashboard card escapes every value it prints.

If you believe you have found a security issue, please report it privately via [GitHub Security Advisories](../../security/advisories/new) rather than opening a public issue. For anything else, please use the regular [Issues](../../issues) tab.
