# Streetwise NOLA

A lightweight live dashboard for New Orleans Streetwise ArcGIS data.

This project is a static web app that queries the public Streetwise ArcGIS REST service and plots active roadway reports on a Leaflet map.

## Current v0 features

- Live ArcGIS REST queries
- Known Streetwise flooding layer support
- Configurable layer IDs so traffic incidents or sensor layers can be added quickly
- Leaflet map with clickable report markers
- Side panel with report cards and timestamps
- Manual refresh and optional auto-refresh
- Service metadata/debug panel for digging into available layers and fields

## Known data source

Base service:

```text
https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer
```

Known working query discovered from Streetwise:

```text
https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer/1/query?f=json&where=1%3D1&returnGeometry=true&spatialRel=esriSpatialRelIntersects&outFields=Address%2CCommonName%2CTimeCreate&outSR=102100
```

In this app, layer queries use `outFields=*` and request `outSR=4326` so coordinates can be plotted directly as latitude/longitude when the service supports it.

## Files

- `index.html` - app shell
- `style.css` - dark dashboard styling
- `app.js` - ArcGIS queries, map, layer rendering, and refresh logic

## Run locally

Open `index.html` directly, or run a small static server from the repo folder:

```bash
python -m http.server 8000
```

Then open:

```text
http://localhost:8000
```

## GitHub Pages

This should work as a GitHub Pages static site.

1. Go to repo Settings
2. Pages
3. Source: Deploy from a branch
4. Branch: `main`
5. Folder: `/root`

## Next targets

- Confirm every MapServer layer from the service metadata endpoint
- Add verified traffic incident layer fields
- Search for hidden or separate Hyfi/raw water sensor feeds
- Add hydrographs if sensor time-series data becomes available
- Add optional rainfall/radar/QPE overlays later

## Notes

This is not an official City of New Orleans product. It is a lightweight public-data viewer for situational awareness and experimentation.
