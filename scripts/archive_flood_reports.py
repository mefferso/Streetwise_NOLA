#!/usr/bin/env python3
"""Archive and deduplicate active Streetwise NOLA flood reports."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SERVICE_URL = "https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer"
FLOOD_LAYER_ID = 1
LOCAL_ZONE = ZoneInfo("America/Chicago")
OUT_DIR = Path("data")
ARCHIVE_DIR = OUT_DIR / "archive"
EVENTS_DIR = OUT_DIR / "events"
LATEST_PATH = OUT_DIR / "latest_flood_reports.json"
HEARTBEAT_INTERVAL_SECONDS = 6 * 60 * 60


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
    request = urllib.request.Request(url, headers={"User-Agent": "Streetwise-NOLA-Archive/2.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(json.dumps(data["error"], indent=2))
    return data


def web_mercator_to_latlon(x: float, y: float) -> tuple[float, float]:
    lon = (x / 20037508.34) * 180.0
    lat = (y / 20037508.34) * 180.0
    lat = (180.0 / math.pi) * (2.0 * math.atan(math.exp((lat * math.pi) / 180.0)) - math.pi / 2.0)
    return lat, lon


def get_latlon(geometry: dict[str, Any]) -> tuple[float | None, float | None]:
    x, y = geometry.get("x"), geometry.get("y")
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


def event_id_for(attrs: dict[str, Any], address: Any, time_create: Any) -> str:
    incident = first_present(attrs, ["Incident", "incident"])
    if incident:
        return f"incident-{incident}"
    object_id = first_present(attrs, ["ESRI_OID", "OBJECTID", "ObjectId", "objectid", "FID"])
    if object_id is not None:
        return f"oid-{object_id}"
    seed = f"{address}|{time_create}|{attrs.get('MapX')}|{attrs.get('MapY')}"
    return "fallback-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def normalize_feature(feature: dict[str, Any]) -> dict[str, Any]:
    attrs = feature.get("attributes") or {}
    lat, lon = get_latlon(feature.get("geometry") or {})
    title = first_present(attrs, ["CommonName", "commonname", "Type", "type", "Description", "Address"])
    address = first_present(attrs, ["Address", "address", "Location", "location", "Street", "Block"])
    time_create = first_present(attrs, ["TimeCreate", "timecreate", "CreateDate", "Created", "Updated", "LastUpdate"])
    return {
        "event_id": event_id_for(attrs, address, time_create),
        "incident": first_present(attrs, ["Incident", "incident"]),
        "object_id": first_present(attrs, ["ESRI_OID", "OBJECTID", "ObjectId", "objectid", "FID"]),
        "title": title,
        "address": address,
        "time_create": time_create,
        "time_create_utc": first_present(attrs, ["TimeCreateUTC", "timecreateutc"]),
        "lat": lat,
        "lon": lon,
        "attributes": attrs,
    }


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def main() -> int:
    run_time = datetime.now(timezone.utc)
    run_iso = run_time.isoformat().replace("+00:00", "Z")
    local_date = run_time.astimezone(LOCAL_ZONE).date().isoformat()
    query_url = build_query_url()
    features = fetch_json(query_url).get("features") or []
    reports = sorted(
        (normalize_feature(feature) for feature in features),
        key=lambda report: report["event_id"],
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)

    snapshot = {
        "run_time_utc": run_iso,
        "local_date": local_date,
        "source_url": query_url,
        "service_url": SERVICE_URL,
        "layer_id": FLOOD_LAYER_ID,
        "feature_count": len(reports),
        "reports": reports,
    }
    previous_snapshot = load_json(LATEST_PATH, {})
    previous_reports = previous_snapshot.get("reports")
    previous_run_raw = previous_snapshot.get("run_time_utc")
    try:
        previous_run = datetime.fromisoformat(previous_run_raw.replace("Z", "+00:00")) if previous_run_raw else None
    except (TypeError, ValueError):
        previous_run = None

    reports_changed = previous_reports != reports
    new_local_day = previous_snapshot.get("local_date") != local_date
    heartbeat_due = (
        previous_run is None
        or (run_time - previous_run).total_seconds() >= HEARTBEAT_INTERVAL_SECONDS
    )
    capture_snapshot = reports_changed or new_local_day or heartbeat_due

    if capture_snapshot:
        LATEST_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        daily_snapshot_path = ARCHIVE_DIR / f"{local_date}.jsonl"
        with daily_snapshot_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, sort_keys=True) + "\n")

    events_path = EVENTS_DIR / f"{local_date}.json"
    catalog_existed = events_path.exists()
    catalog = load_json(events_path, {
        "date": local_date,
        "timezone": "America/Chicago",
        "last_archive_run_utc": run_iso,
        "event_count": 0,
        "events": [],
    })
    original_catalog = {
        key: value for key, value in catalog.items()
        if key != "last_archive_run_utc"
    }
    events_by_id = {event["event_id"]: event for event in catalog.get("events", [])}

    for event in events_by_id.values():
        event["active"] = False

    for report in reports:
        event_id = report["event_id"]
        existing = events_by_id.get(event_id)
        if existing:
            first_seen = existing["first_seen_utc"]
            observations = int(existing.get("observations", 0)) + 1
        else:
            first_seen = run_iso
            observations = 1
        events_by_id[event_id] = {
            **report,
            "first_seen_utc": first_seen,
            "last_seen_utc": run_iso,
            "observations": observations,
            "active": True,
        }

    events = sorted(
        events_by_id.values(),
        key=lambda event: (event.get("time_create_utc") or event.get("time_create") or 0),
        reverse=True,
    )
    catalog.update({
        "last_archive_run_utc": run_iso,
        "event_count": len(events),
        "active_count": sum(1 for event in events if event.get("active")),
        "events": events,
    })
    updated_catalog = {
        key: value for key, value in catalog.items()
        if key != "last_archive_run_utc"
    }
    catalog_changed = not catalog_existed or updated_catalog != original_catalog
    if catalog_changed:
        events_path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    snapshot_status = "captured" if capture_snapshot else "unchanged; raw snapshot skipped"
    catalog_status = "updated" if catalog_changed else "unchanged"
    print(f"Checked {len(reports)} active reports; raw snapshot {snapshot_status}")
    print(f"Daily event catalog {catalog_status}: {events_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Archive failed: {exc}", file=sys.stderr)
        raise
