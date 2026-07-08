# Streetwise NOLA

A lightweight live dashboard for New Orleans Streetwise flood reports.

This project is a static web app that queries the public Streetwise ArcGIS REST service and plots active reported street flooding on a Leaflet map.

## Current v0 features

- Live ArcGIS REST queries
- Streetwise reported flooding layer only
- Leaflet map with clickable flood report markers
- Side panel with report cards and timestamps
- Manual refresh and optional auto-refresh
- Service metadata/debug panel for digging into available layers and fields
- Optional GitHub Actions archive of active flood reports

## Known data source

Base service:

```text
https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer
```

Known reported flooding layer:

```text
MapServer/1
```

Known working query discovered from Streetwise:

```text
https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer/1/query?f=json&where=1%3D1&returnGeometry=true&spatialRel=esriSpatialRelIntersects&outFields=Address%2CCommonName%2CTimeCreate&outSR=102100
```

In this app, layer queries use `outFields=*` and request `outSR=4326` so coordinates can be plotted directly as latitude/longitude when the service supports it.

## Archive

The repo includes a GitHub Actions workflow that can archive the current active flood reports every 15 minutes.

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
```

Important: this archive only captures whatever the public Streetwise flood layer returns at each run. It is not a historical backfill and it is not raw Hyfi sensor telemetry unless that data eventually appears in the public layer.

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

- Confirm every MapServer layer from the service metadata endpoint
- Search for hidden or separate Hyfi/raw water sensor feeds
- Add hydrographs if sensor time-series data becomes available
- Add optional rainfall/radar/QPE overlays later

## Notes

This is not an official City of New Orleans product. It is a lightweight public-data viewer for situational awareness and experimentation.
