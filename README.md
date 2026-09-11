# Déjà Flood

Puddle Intelligence for Southeast Louisiana — a lightweight live and archived dashboard for New Orleans Streetwise flood reports.

This project is a static web app that queries the City of New Orleans' public 21F ArcGIS service and plots active reported street flooding on a Leaflet map.

## Current v0 features

- Live ArcGIS REST queries
- Streetwise reported flooding layer only
- Leaflet map with clickable flood report markers
- Side panel with report cards and timestamps
- Manual refresh and optional auto-refresh
- Optional GitHub Actions archive of active flood reports

## Current data source

Base service:

```text
https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/Flooding/MapServer
```

Layers used by the app and archive:

```text
MapServer/1  Flooded Streets (Live 21F)
MapServer/2  21F Last 24 Hours
MapServer/3  21F Historical All Time
```

Example live query:

```text
https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/Flooding/MapServer/1/query?f=json&where=1%3D1&returnGeometry=true&outFields=%2A&outSR=4326
```

The old `Streetwise/Streetwise_Live/MapServer/1` source stopped returning flood
features after July 11, 2026 while its traffic layer remained live. The temporary
`Staging/Flood_Events` source also had no records after that date. A September
2026 forensic review found the separate `Rainwater/Flooding` service, whose
all-time layer contains one publicly recoverable post-cutoff report from
September 4, 2026. The archive now uses that service for live capture and daily
historical reconciliation.

City CAD's `TimeCreate` field is a New Orleans wall clock serialized in a
UTC-shaped value. The archiver preserves that convention and derives true UTC
when `TimeCreateUTC` is absent.

## Archive

The repo includes a GitHub Actions workflow that checks the live and last-24-hour
flood layers every 10 minutes. Raw snapshots are saved only when the report set
changes, at the start of a new local day, or as a six-hour heartbeat. A daily
reconciliation against the all-time layer catches short-lived events that a
scheduled poll may miss.

Workflow:

```text
.github/workflows/archive-flood-reports.yml
```

Script:

```text
scripts/archive_flood_reports.py
```

Generated files after the workflow runs:

```text
data/latest_flood_reports.json
data/archive/YYYY-MM-DD.jsonl
data/events/YYYY-MM-DD.json
data/archive_index.json
```

Important: this archive captures only what the public City layers publish. It is
not raw HYFI/underpass sensor telemetry, and the public historical layer does not
contain most 21F reports missing between July 12 and September 11, 2026.

## Files

- `index.html` - app shell
- `style.css` - dark dashboard styling
- `app.js` - ArcGIS queries, map, flood layer rendering, and refresh logic
- `scripts/archive_flood_reports.py` - archive script
- `.github/workflows/archive-flood-reports.yml` - scheduled archive workflow

## Run locally

Open `index.html` directly, or run a small static server from the repo folder:

```bash
python -m http.server 8000
```

Then open:

```text
http://localhost:8000
```

## Run the archive locally

```bash
python scripts/archive_flood_reports.py
```

## GitHub Pages

This should work as a GitHub Pages static site.

1. Go to repo Settings
2. Pages
3. Source: Deploy from a branch
4. Branch: `main`
5. Folder: `/root`

## GitHub Actions archive setup

The workflow is already committed. Make sure Actions are enabled for the repo. You can also run it manually from the Actions tab using `workflow_dispatch`.

## Next targets

- Monitor the Rainwater history layer for delayed City backfills
- Request an authoritative 21F export from the City's CAD/GIS administrators for the remaining July 12–present gap
- Add hydrographs if sensor time-series data becomes available
- Add optional rainfall/radar/QPE overlays later

## Notes

This is not an official City of New Orleans product. It is a lightweight public-data viewer for situational awareness and experimentation.
