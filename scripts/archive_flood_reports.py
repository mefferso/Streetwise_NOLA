#!/usr/bin/env python3
"""Archive active Streetwise NOLA flood reports.

This script queries the public Streetwise ArcGIS layer for reported street flooding,
normalizes the response, writes the latest snapshot, and appends one JSON line per
run to a daily archive file.
"""

from __future__ import annotations

import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SERVICE_URL = "https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer"
FLOOD_LAYER_ID = 1
OUT_DIR = Path("data")
ARCHIVE_DIR = OUT_DIR / "archive"
LATEST_PATH = OUT_DIR / "latest_flood_reports.json"


def build_query_url() -> str:
    params = {
        "f": "json",
        "where": "1=1",
        "returnGeometry": "true",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "outSR": "4326",
    }
    return f"{SERVICE_URL}/{FLOOD_LAYER_ID}/query?{urllib.parse.urlencode(params)}"


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Streetwise-NOLA-Archive/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if "error" in data:
        raise RuntimeError(json.dumps(data["error"], indent=2))
    return data


def web_mercator_to_latlon(x: float, y: float) -> tuple[float, float]:
    lon = (x / 20037508.34) * 180.0
    lat = (y / 20037508.34) * 180.0
    lat = (180.0 / math.pi) * (2.0 * math.atan(math.exp((lat * math.pi) / 180.0)) - math.pi / 2.0)
    return lat, lon


def get_latlon(geometry: dict[str, Any]) -> tuple[float | None, float | None]:
    x = geometry.get("x")
    y = geometry.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None, None
    if abs(x) <= 180 and abs(y) <= 90:
        return float(y), float(x)
    return web_mercator_to_latlon(float(x), float(y))


def first_present(attrs: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = attrs.get(key)
        if value not in (None, ""):
            return value
    return None


def normalize_feature(feature: dict[str, Any]) -> dict[str, Any]:
    attrs = feature.get("attributes") or {}
    geometry = feature.get("geometry") or {}
    lat, lon = get_latlon(geometry)
    object_id = first_present(attrs, ["OBJECTID", "ObjectId", "objectid", "FID"])
    title = first_present(attrs, ["CommonName", "commonname", "Type", "type", "Description", "Address"])
    address = first_present(attrs, ["Address", "address", "Location", "location", "Street", "Block"])
    time_create = first_present(attrs, ["TimeCreate", "timecreate", "CreateDate", "Created", "Updated", "LastUpdate"])

    return {
        "object_id": object_id,
        "title": title,
        "address": address,
        "time_create": time_create,
        "lat": lat,
        "lon": lon,
        "attributes": attrs,
    }


def main() -> int:
    run_time = datetime.now(timezone.utc)
    run_iso = run_time.isoformat().replace("+00:00", "Z")
    query_url = build_query_url()
    data = fetch_json(query_url)
    features = data.get("features") or []
    reports = [normalize_feature(feature) for feature in features]

    snapshot = {
        "run_time_utc": run_iso,
        "source_url": query_url,
        "service_url": SERVICE_URL,
        "layer_id": FLOOD_LAYER_ID,
        "feature_count": len(reports),
        "reports": reports,
        "raw_feature_count": len(features),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    LATEST_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    daily_path = ARCHIVE_DIR / f"{run_time:%Y-%m-%d}.jsonl"
    with daily_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, sort_keys=True) + "\n")

    print(f"Archived {len(reports)} flood reports at {run_iso}")
    print(f"Latest: {LATEST_PATH}")
    print(f"Daily archive: {daily_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Archive failed: {exc}", file=sys.stderr)
        raise
