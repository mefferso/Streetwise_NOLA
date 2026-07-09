#!/usr/bin/env python3
"""Try to backfill Streetwise NOLA flood reports for a recent lookback window.

This tests whether the public Streetwise ArcGIS flood layer can return older
features using TimeCreate filters. It also runs a current/live `where=1=1`
query in the same run so we can compare active features against the time-filtered
lookback result.
"""

from __future__ import annotations

import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SERVICE_URL = "https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer"
FLOOD_LAYER_ID = 1
LOOKBACK_DAYS = 30
OUT_DIR = Path("data")
BACKFILL_DIR = OUT_DIR / "backfill"
BACKFILL_PATH = BACKFILL_DIR / "last_30_days_flood_reports.json"
SUMMARY_PATH = BACKFILL_DIR / "last_30_days_summary.json"
CURRENT_PATH = BACKFILL_DIR / "current_layer_snapshot.json"
LAYER_METADATA_PATH = BACKFILL_DIR / "layer_1_metadata.json"

TIME_FIELDS_TO_TRY = [
    "TimeCreate",
    "timecreate",
    "CreateDate",
    "created_date",
    "Created",
    "created",
    "Updated",
    "LastUpdate",
]


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Streetwise-NOLA-Backfill/1.1"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if "error" in data:
        raise RuntimeError(json.dumps(data["error"], indent=2))
    return data


def build_query_url(
    where: str,
    result_offset: int = 0,
    result_record_count: int = 2000,
    order_by_fields: str | None = None,
) -> str:
    params = {
        "f": "json",
        "where": where,
        "returnGeometry": "true",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "outSR": "4326",
        "resultOffset": str(result_offset),
        "resultRecordCount": str(result_record_count),
    }
    if order_by_fields:
        params["orderByFields"] = order_by_fields
    return f"{SERVICE_URL}/{FLOOD_LAYER_ID}/query?{urllib.parse.urlencode(params)}"


def build_layer_metadata_url() -> str:
    return f"{SERVICE_URL}/{FLOOD_LAYER_ID}?f=pjson"


def arcgis_timestamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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
    lat, lon = get_latlon(feature.get("geometry") or {})
    return {
        "object_id": first_present(attrs, ["OBJECTID", "ObjectId", "objectid", "FID"]),
        "title": first_present(attrs, ["CommonName", "commonname", "Type", "type", "Description", "Address"]),
        "address": first_present(attrs, ["Address", "address", "Location", "location", "Street", "Block"]),
        "time_create": first_present(attrs, ["TimeCreate", "timecreate", "CreateDate", "Created", "Updated", "LastUpdate"]),
        "lat": lat,
        "lon": lon,
        "attributes": attrs,
    }


def dedupe_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for report in reports:
        object_id = report.get("object_id")
        if object_id is not None:
            key = f"object:{object_id}"
        else:
            key = json.dumps(
                [report.get("title"), report.get("address"), report.get("time_create"), report.get("lat"), report.get("lon")],
                sort_keys=True,
                default=str,
            )
        if key in seen:
            continue
        seen.add(key)
        unique.append(report)
    return unique


def summarize_fields_from_metadata(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    fields = metadata.get("fields") or []
    return [
        {
            "name": field.get("name"),
            "type": field.get("type"),
            "alias": field.get("alias"),
            "nullable": field.get("nullable"),
            "editable": field.get("editable"),
        }
        for field in fields
    ]


def query_current_layer() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    where = "1=1"
    url = build_query_url(where)
    data = fetch_json(url)
    features = data.get("features") or []
    reports = [normalize_feature(feature) for feature in features]
    summary = {
        "query_type": "current_live_layer",
        "where": where,
        "query_url": url,
        "feature_count": len(features),
        "exceeded_transfer_limit": data.get("exceededTransferLimit", False),
        "fields_returned": sorted(list((features[0].get("attributes") or {}).keys())) if features else [],
    }
    return reports, summary


def try_where(field_name: str, start: datetime, end: datetime) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    start_text = arcgis_timestamp(start)
    end_text = arcgis_timestamp(end)
    where = f"{field_name} >= timestamp '{start_text}' AND {field_name} <= timestamp '{end_text}'"
    url = build_query_url(where, order_by_fields=f"{field_name} DESC")
    data = fetch_json(url)
    features = data.get("features") or []
    reports = [normalize_feature(feature) for feature in features]
    summary = {
        "query_type": "time_filtered_lookback",
        "field_tested": field_name,
        "where": where,
        "query_url": url,
        "feature_count": len(features),
        "exceeded_transfer_limit": data.get("exceededTransferLimit", False),
        "fields_returned": sorted(list((features[0].get("attributes") or {}).keys())) if features else [],
    }
    return where, reports, summary


def main() -> int:
    run_time = datetime.now(timezone.utc)
    start = run_time - timedelta(days=LOOKBACK_DAYS)

    summaries: list[dict[str, Any]] = []
    all_reports: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    try:
        metadata = fetch_json(build_layer_metadata_url())
    except Exception as exc:
        metadata = {"metadata_error": str(exc)}
        errors.append({"field_tested": "layer_metadata", "error": str(exc)})

    try:
        current_reports, current_summary = query_current_layer()
        summaries.append(current_summary)
    except Exception as exc:
        current_reports = []
        errors.append({"field_tested": "current_live_layer_where_1_equals_1", "error": str(exc)})

    for field_name in TIME_FIELDS_TO_TRY:
        try:
            _where, reports, summary = try_where(field_name, start, run_time)
            summaries.append(summary)
            if reports:
                all_reports.extend(reports)
        except Exception as exc:
            errors.append({"field_tested": field_name, "error": str(exc)})

    unique_reports = dedupe_reports(all_reports)

    output = {
        "run_time_utc": run_time.isoformat().replace("+00:00", "Z"),
        "lookback_days": LOOKBACK_DAYS,
        "start_time_utc": start.isoformat().replace("+00:00", "Z"),
        "end_time_utc": run_time.isoformat().replace("+00:00", "Z"),
        "service_url": SERVICE_URL,
        "layer_id": FLOOD_LAYER_ID,
        "metadata_summary": {
            "name": metadata.get("name"),
            "type": metadata.get("type"),
            "geometry_type": metadata.get("geometryType"),
            "object_id_field": metadata.get("objectIdField"),
            "time_info": metadata.get("timeInfo"),
            "fields": summarize_fields_from_metadata(metadata),
        },
        "summary": summaries,
        "errors": errors,
        "current_live_record_count": len(current_reports),
        "total_time_filtered_records_before_dedupe": len(all_reports),
        "total_time_filtered_unique_records": len(unique_reports),
        "reports": unique_reports,
    }

    current_output = {
        "run_time_utc": run_time.isoformat().replace("+00:00", "Z"),
        "service_url": SERVICE_URL,
        "layer_id": FLOOD_LAYER_ID,
        "feature_count": len(current_reports),
        "reports": current_reports,
    }
    summary_output = {key: value for key, value in output.items() if key != "reports"}

    BACKFILL_DIR.mkdir(parents=True, exist_ok=True)
    BACKFILL_PATH.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    SUMMARY_PATH.write_text(json.dumps(summary_output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    CURRENT_PATH.write_text(json.dumps(current_output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    LAYER_METADATA_PATH.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Backfill test complete. Current/live records: {len(current_reports)}")
    print(f"Backfill test complete. Time-filtered unique records found: {len(unique_reports)}")
    print(f"Wrote: {BACKFILL_PATH}")
    print(f"Wrote: {SUMMARY_PATH}")
    print(f"Wrote: {CURRENT_PATH}")
    print(f"Wrote: {LAYER_METADATA_PATH}")
    if errors:
        print("Some field tests failed:")
        for error in errors:
            print(f"- {error['field_tested']}: {error['error']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Backfill failed: {exc}", file=sys.stderr)
        raise
