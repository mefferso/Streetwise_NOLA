#!/usr/bin/env python3
"""Archive Streetwise NOLA flood reports from the current City GIS service.

The original eocgis Streetwise_Live service stopped returning flood features after
July 11, 2026 while still returning successful/empty responses.  Streetwise now
publishes flood data from the City's Staging/Flood_Events MapServer.  This
archiver uses the 48-hour layer for reliable near-real-time capture and performs
a daily sync from the historic layer so short-lived events are not lost.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SERVICE_URL = "https://gis.nola.gov/arcgis/rest/services/Staging/Flood_Events/MapServer"
LIVE_LAYER_ID = 1          # 21 F - Last 4 hours
RECENT_LAYER_ID = 3        # 21 F - Last 48 hours
HISTORIC_LAYER_ID = 4      # 21 F - Historic Flood Incidents
LOCAL_ZONE = ZoneInfo("America/Chicago")
OUT_DIR = Path("data")
ARCHIVE_DIR = OUT_DIR / "archive"
EVENTS_DIR = OUT_DIR / "events"
LATEST_PATH = OUT_DIR / "latest_flood_reports.json"
INDEX_PATH = OUT_DIR / "archive_index.json"
HISTORIC_STATE_PATH = OUT_DIR / "historic_sync_state.json"
HEARTBEAT_INTERVAL_SECONDS = 6 * 60 * 60
HISTORIC_SYNC_INTERVAL_SECONDS = 24 * 60 * 60
HISTORIC_LOOKBACK_DAYS = 180
PAGE_SIZE = 1000

COMMENT_TIMESTAMP_RE = re.compile(
    r"(20\d{2})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?"
)


def build_query_url(layer_id: int, *, offset: int = 0) -> str:
    params = {
        "f": "json",
        "where": "1=1",
        "returnGeometry": "true",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "outSR": "4326",
        "resultOffset": str(offset),
        "resultRecordCount": str(PAGE_SIZE),
    }
    return f"{SERVICE_URL}/{layer_id}/query?{urllib.parse.urlencode(params)}"


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Streetwise-NOLA-Archive/3.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = json.loads(response.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(json.dumps(data["error"], indent=2))
    return data


def fetch_layer(layer_id: int) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        data = fetch_json(build_query_url(layer_id, offset=offset))
        page = data.get("features") or []
        features.extend(page)
        if not data.get("exceededTransferLimit") and len(page) < PAGE_SIZE:
            break
        if not page:
            break
        offset += len(page)
    return features


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


def parse_local_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, timezone.utc).astimezone(LOCAL_ZONE)

    text = str(value).strip()
    if not text:
        return None

    # ISO-like values first.
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=LOCAL_ZONE)
        return parsed.astimezone(LOCAL_ZONE)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=LOCAL_ZONE)
        except ValueError:
            continue
    return None


def event_datetime(attrs: dict[str, Any]) -> datetime | None:
    # The newer Flood_Events service often embeds the incident timestamp in
    # Comments. Prefer that over TimeClosed so events land on the day they began.
    comments = str(attrs.get("Comments") or "")
    match = COMMENT_TIMESTAMP_RE.search(comments)
    if match:
        year, month, day, hour, minute, second = match.groups()
        return datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second or 0),
            tzinfo=LOCAL_ZONE,
        )

    for key in (
        "TimeCreateUTC", "TimeCreate", "OpenedDateTime", "openedDateTime",
        "TimeClosed", "closedDateTime", "ClosedDateTime",
    ):
        parsed = parse_local_datetime(attrs.get(key))
        if parsed:
            return parsed
    return None


def stable_event_id(attrs: dict[str, Any], address: Any, when: datetime | None) -> str:
    incident = first_present(attrs, ["Incident", "incident", "CaseRef", "caseRef"])
    if incident:
        return f"incident-{incident}"
    seed = "|".join([
        str(address or "").strip().upper(),
        when.isoformat() if when else "",
        str(attrs.get("Comments") or "").strip(),
    ])
    if seed.strip("|"):
        return "event-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]
    object_id = first_present(attrs, ["OBJECTID", "ESRI_OID", "ObjectId", "objectid", "FID"])
    return f"oid-{object_id}" if object_id is not None else "event-unknown"


def normalize_feature(feature: dict[str, Any], source_layer: int) -> dict[str, Any]:
    attrs = feature.get("attributes") or {}
    lat, lon = get_latlon(feature.get("geometry") or {})
    address = first_present(attrs, ["Address", "address", "Location", "location", "Street", "Block"])
    when = event_datetime(attrs)
    title = first_present(attrs, ["CommonName", "Title", "TypeText", "Type", "Description", "Address"])
    return {
        "event_id": stable_event_id(attrs, address, when),
        "incident": first_present(attrs, ["Incident", "incident", "CaseRef"]),
        "object_id": first_present(attrs, ["OBJECTID", "ESRI_OID", "ObjectId", "objectid", "FID"]),
        "title": title,
        "address": address,
        "time_create": int(when.timestamp() * 1000) if when else None,
        "time_create_utc": int(when.astimezone(timezone.utc).timestamp() * 1000) if when else None,
        "event_time_local": when.isoformat() if when else None,
        "lat": lat,
        "lon": lon,
        "attributes": attrs,
        "source_layer": source_layer,
    }


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def historic_sync_due(run_time: datetime) -> bool:
    state = load_json(HISTORIC_STATE_PATH, {})
    raw = state.get("last_success_utc")
    if not raw:
        return True
    try:
        previous = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return True
    return (run_time - previous).total_seconds() >= HISTORIC_SYNC_INTERVAL_SECONDS


def merge_catalog_event(
    report: dict[str, Any],
    *,
    run_iso: str,
    active_ids: set[str],
    fallback_date: str,
) -> tuple[str, bool]:
    when = parse_local_datetime(report.get("event_time_local"))
    event_date = when.date().isoformat() if when else fallback_date
    events_path = EVENTS_DIR / f"{event_date}.json"
    catalog = load_json(events_path, {
        "date": event_date,
        "timezone": "America/Chicago",
        "last_archive_run_utc": run_iso,
        "event_count": 0,
        "active_count": 0,
        "events": [],
    })
    before = json.dumps(catalog, sort_keys=True)
    events_by_id = {event.get("event_id"): event for event in catalog.get("events", []) if event.get("event_id")}

    event_id = report["event_id"]
    existing = events_by_id.get(event_id)
    first_seen = existing.get("first_seen_utc") if existing else None
    if not first_seen:
        first_seen = report.get("event_time_local") or run_iso
    observations = int(existing.get("observations", 0)) + 1 if existing else 1

    events_by_id[event_id] = {
        **report,
        "first_seen_utc": first_seen,
        "last_seen_utc": run_iso if event_id in active_ids else (existing.get("last_seen_utc") if existing else (report.get("event_time_local") or run_iso)),
        "observations": observations,
        "active": event_id in active_ids,
    }

    events = sorted(
        events_by_id.values(),
        key=lambda event: event.get("time_create_utc") or 0,
        reverse=True,
    )
    catalog.update({
        "last_archive_run_utc": run_iso,
        "event_count": len(events),
        "active_count": sum(1 for event in events if event.get("active")),
        "events": events,
    })
    after = json.dumps(catalog, sort_keys=True)
    if after != before:
        events_path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return event_date, True
    return event_date, False


def rebuild_index() -> None:
    dates: list[dict[str, Any]] = []
    for path in sorted(EVENTS_DIR.glob("*.json")):
        catalog = load_json(path, {})
        count = int(catalog.get("event_count") or 0)
        if count:
            dates.append({
                "date": catalog.get("date") or path.stem,
                "event_count": count,
                "active_count": int(catalog.get("active_count") or 0),
            })
    payload = {
        "timezone": "America/Chicago",
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dates": dates,
    }
    INDEX_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    run_time = datetime.now(timezone.utc)
    run_iso = run_time.isoformat().replace("+00:00", "Z")
    local_date = run_time.astimezone(LOCAL_ZONE).date().isoformat()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)

    live_features = fetch_layer(LIVE_LAYER_ID)
    recent_features = fetch_layer(RECENT_LAYER_ID)
    live_reports = [normalize_feature(feature, LIVE_LAYER_ID) for feature in live_features]
    recent_reports = [normalize_feature(feature, RECENT_LAYER_ID) for feature in recent_features]
    active_ids = {report["event_id"] for report in live_reports}

    # Current snapshot is based on the 48-hour layer.  This is deliberately more
    # forgiving than the old "active only" source and protects against short events.
    reports = sorted(recent_reports, key=lambda report: report.get("time_create_utc") or 0, reverse=True)
    snapshot = {
        "run_time_utc": run_iso,
        "local_date": local_date,
        "source_url": build_query_url(RECENT_LAYER_ID),
        "service_url": SERVICE_URL,
        "layer_id": RECENT_LAYER_ID,
        "feature_count": len(reports),
        "reports": reports,
    }
    previous_snapshot = load_json(LATEST_PATH, {})
    previous_reports = previous_snapshot.get("reports")
    previous_run_raw = previous_snapshot.get("run_time_utc")
    try:
        previous_run = datetime.fromisoformat(str(previous_run_raw).replace("Z", "+00:00")) if previous_run_raw else None
    except ValueError:
        previous_run = None

    reports_changed = previous_reports != reports
    new_local_day = previous_snapshot.get("local_date") != local_date
    heartbeat_due = previous_run is None or (run_time - previous_run).total_seconds() >= HEARTBEAT_INTERVAL_SECONDS
    capture_snapshot = reports_changed or new_local_day or heartbeat_due
    if capture_snapshot:
        LATEST_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        daily_snapshot_path = ARCHIVE_DIR / f"{local_date}.jsonl"
        with daily_snapshot_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, sort_keys=True) + "\n")

    changed_dates: set[str] = set()
    for report in recent_reports:
        date_value, changed = merge_catalog_event(
            report, run_iso=run_iso, active_ids=active_ids, fallback_date=local_date
        )
        if changed:
            changed_dates.add(date_value)

    historic_count = 0
    if historic_sync_due(run_time):
        historic_features = fetch_layer(HISTORIC_LAYER_ID)
        historic_reports = [normalize_feature(feature, HISTORIC_LAYER_ID) for feature in historic_features]
        cutoff = run_time.astimezone(LOCAL_ZONE) - timedelta(days=HISTORIC_LOOKBACK_DAYS)
        for report in historic_reports:
            when = parse_local_datetime(report.get("event_time_local"))
            if when and when < cutoff:
                continue
            date_value, changed = merge_catalog_event(
                report, run_iso=run_iso, active_ids=active_ids, fallback_date=local_date
            )
            if changed:
                changed_dates.add(date_value)
            historic_count += 1
        HISTORIC_STATE_PATH.write_text(json.dumps({
            "last_success_utc": run_iso,
            "service_url": SERVICE_URL,
            "layer_id": HISTORIC_LAYER_ID,
            "records_considered": historic_count,
            "lookback_days": HISTORIC_LOOKBACK_DAYS,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    rebuild_index()
    snapshot_status = "captured" if capture_snapshot else "unchanged; raw snapshot skipped"
    print(f"Live 4-hour records: {len(live_reports)}")
    print(f"Recent 48-hour records: {len(recent_reports)}; raw snapshot {snapshot_status}")
    if historic_count:
        print(f"Historic sync considered {historic_count} recent records")
    print(f"Event catalogs changed for {len(changed_dates)} date(s)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Archive failed: {exc}", file=sys.stderr)
        raise
