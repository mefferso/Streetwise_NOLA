# Supplemental flood-awareness feeds

The original 21F live/24-hour/history viewer and its `data/events` archive remain unchanged.

The viewer separately requests:

- `Rainwater/FWS_WaterLevel/MapServer/0` — **underpass water-level observations**, not verified closures or 21F calls.
- `https://gis.nola.gov/apps/flood_alerts/api/get_alerts` — **City flood alerts**, where publicly accessible.

The supplemental panel shows response health independently. A failed request or unrecognized response is **DATA INCOMPLETE**, not zero incidents. Sensor values are deliberately not interpreted as closure states, and neither feed is mixed into the 21F incident archive.

**Important validation gap:** These City endpoints could not be queried successfully from the implementation environment. Confirm actual response schemas, cross-origin access, and the Canal Underpass 2026-10-31 10:25 CDT report before claiming completeness. The panel supports ArcGIS and common GeoJSON/alerts arrays conservatively, without inventing geolocations or timestamps. Supplemental information remains **live only**; there is no separate supplemental archive yet.

Next: capture the October 31 incident's actual network response from the City's Streetwise browser app, identify its authoritative category/source, write schema fixtures and tests, and only then add a clearly separate supplemental archive and closure indicator.
