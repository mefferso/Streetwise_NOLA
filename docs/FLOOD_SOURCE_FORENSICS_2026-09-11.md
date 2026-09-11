# Streetwise NOLA flood-source forensics — 2026-09-11

## Executive conclusion

The missing Streetwise flood reports from **2026-07-12 through 2026-09-11** cannot be fully reconstructed from the public City feeds that are currently reachable.

This is not primarily a viewer bug or a Git-history problem. The public 911/CAD flood publishing chain appears to have stopped or changed after 2026-07-11, while the City's own Streetwise front end continued to point at the now-empty legacy flood layer. A second City service (`Rainwater/Flooding`) preserves a much larger 21F history, but it contains only **one unique 21F incident after 2026-07-11** in the missing period (2026-09-04). The City `Staging/Flood_Events` historic layer does not contain the missing 2026 events either.

The repository has been changed to use the best currently public 21F source for future capture (`Rainwater/Flooding`, including live/24-hour/history reconciliation), and the one publicly recoverable post-cutoff incident has been backfilled. Recovering the rest requires an authoritative CAD/911/GIS export or restoration of the City's missing 21F history.

## What was tested

### 1. Original Streetwise service

`https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer`

- Flood layer 1 stopped returning flood features after 2026-07-11.
- Historical repo snapshots from 2026-07-12 already recorded zero features, so later code changes did not erase those reports.
- Other non-flood Streetwise/CAD layers continued to publish records after the cutoff, which points to a flood-specific publishing/data-path failure rather than the entire ArcGIS environment disappearing.

### 2. Current official Streetwise web application

The live `streetwise.nola.gov` JavaScript was inspected directly. Its flood configuration still points to the same legacy `Streetwise_Live/MapServer/1` flood layer. In other words, the City's own public Streetwise application appears to share the same broken/stale flood source.

The application also contains an old, commented fallback to:

`http://cop.nola.gov:6080/arcgis/rest/services/21f_12hours/MapServer/0`

That service now returns an ArcGIS 404 (`Service 21f_12hours/MapServer not found`).

### 3. `Staging/Flood_Events`

`https://gis.nola.gov/arcgis/rest/services/Staging/Flood_Events/MapServer`

The service exposes:

- Last 4 hours
- Last 24 hours
- Last 48 hours
- Historic Flood Incidents
- a 311-related street-flooding group

The historic layer returned 128 records, but all parsed before 2026-07-12. It therefore cannot fill the missing period. Current short-window layers were empty at the time of testing, as expected when no event was active.

### 4. `Rainwater/Flooding` — best public 21F source found

`https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/Flooding/MapServer`

Relevant layers:

- 1 — `Flooded Streets (Live 21F)`
- 2 — `21F Last 24 Hours`
- 3 — `21F Historical All Time`

Layer 3 returned **3,484 raw features / 2,994 unique incidents** after deduplication. However, only **one unique incident** in that public historical set falls after the archive cutoff:

- 2026-09-04 09:35 CDT
- 2800 ESPLANADE AV / CC'S COFFEE
- incident 003630
- type 21F / FLOOD EVENT

That incident has been backfilled into the repository. The public layer does not contain the other known July/August/September 2026 flood calls.

### 5. ArcGIS Online and City GIS discovery

Public ArcGIS Online items and City ArcGIS services were searched for Streetwise, 21F, flood, HYFI, 311, rain, drainage, CAD, and related terms. No alternate public City-owned 911/21F history was found that fills the gap.

Static flood-risk/ponding layers and storm-modeling products are not incident archives and cannot reconstruct the missing calls.

### 6. Live Streetwise auxiliary endpoints

The current Streetwise code also references:

- HYFI flood sensors
- underpass water-level sensors
- a current flood-alert API

These feeds are useful situational data, but they are **sensor/alert data rather than 911/CAD 21F incident calls**. Mixing them into the 21F incident archive would create a false historical equivalence, so they were not used as replacements for the missing calls.

The current flood-alert endpoint returned a valid response with no active features during testing. HYFI is active and returns flood-sensor observations, confirming that the sensor ecosystem is alive even though it is not the missing 911 incident archive.

### 7. New Orleans 311 open data

The public `311 OPCD Calls (2012-Present)` dataset (`2jgv-pqrq`) was queried for 2026-07-12 through 2026-09-11.

- **0 rows** had `request_type` or `request_reason` containing `flood`.
- Drainage requests do exist in the period (for example, 313 `Catch Basin Not Draining` requests), but these are ordinary 311 drainage service requests and are not equivalent to 911 21F flood incidents.

Therefore the 311 open-data feed cannot faithfully recover the missing Streetwise 21F reports.

## Why the gap is real

The public data sources are internally inconsistent with known real-world flooding during the period. There were documented street-flooding/flash-flood events after 2026-07-11, yet the public 21F histories do not contain the corresponding set of calls. That makes a genuine public-data publishing/retention gap much more likely than a period with no flood incidents.

## Repository status now

The archiver now uses the `Rainwater/Flooding` 21F layers instead of depending on the dead legacy Streetwise flood layer. It polls the live/recent layers and reconciles against the historical layer so a transient live report has more than one chance to be captured.

The current archive index contains the original 2026-07-11 event and the one recoverable 2026-09-04 event. This is an honest representation of what is publicly recoverable today; it should not be interpreted as meaning those were the only flood events that occurred.

## Best recovery path

Request an authoritative export from the City of New Orleans / Orleans Parish Communications District / GIS-CAD team for all 911/CAD flood calls from **2026-07-12 00:00 CDT through 2026-09-11 23:59 CDT** (or through the date of export).

The requested filter should be **Type/TypeText = `21F` / `FLOOD EVENT`**, with, at minimum:

- Incident number
- TimeCreated / call time
- TimeClosed if available
- Address
- CommonName / location description
- Comments or public-safe incident description if releasable
- Latitude/longitude or geometry
- disposition/status if available

If the City provides CSV, JSON, GeoJSON, shapefile, or geodatabase output, it can be normalized into the repository's existing `data/events/YYYY-MM-DD.json` format and deduplicated against the already recovered records.

## Diagnostic artifacts added to this repo

The forensic work is reproducible. Diagnostic scripts/results were added for:

- known flood-service probing
- live Streetwise JavaScript endpoint inspection
- alternate live endpoint probing
- ArcGIS Online source discovery
- 311 flood/drainage probing

These are intentionally separate from the production event archive so diagnostic data cannot contaminate the 21F record set.
