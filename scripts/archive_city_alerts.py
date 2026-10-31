#!/usr/bin/env python3
"""Capture public City flood alerts separately from 911/CAD 21F reports.

An absent API record cannot be recreated retrospectively. Do not interpret
empty responses as proof that no closure happened.
"""
import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

URL = "https://gis.nola.gov/apps/flood_alerts/api/get_alerts"
ROOT = Path("data/city_alerts")
LOCAL = ZoneInfo("America/Chicago")


def extract(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("Unexpected flood-alert response")
    if "error" in payload:
        raise ValueError(str(payload["error"]))
    for part in (payload, payload.get("data")):
        if isinstance(part, dict):
            for key in ("features", "alerts"):
                if isinstance(part.get(key), list):
                    return part[key]
    raise ValueError("Unrecognized flood-alert schema")


def event_id(feature):
    props = feature.get("attributes") or feature.get("properties") or feature
    for key in ("alert_id", "AlertID", "incident_id", "Incident", "OBJECTID", "id"):
        if props.get(key) not in (None, ""):
            return str(props[key])
    content = json.dumps(feature, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode()).hexdigest()[:20]


def run(fetch=None, now=None, directory=ROOT):
    now = now or datetime.now(timezone.utc)
    if fetch is None:
        def fetch():
            req = urllib.request.Request(URL, headers={"User-Agent": "DejaFlood-CityAlerts/1.0"})
            with urllib.request.urlopen(req, timeout=35) as response:
                return json.load(response)
    features = extract(fetch())
    directory.mkdir(parents=True, exist_ok=True)
    date = now.astimezone(LOCAL).date().isoformat()
    path = directory / (date + ".json")
    previous = json.loads(path.read_text()) if path.exists() else {}
    known = {a["event_id"]: a for a in previous.get("alerts", [])}
    active = set()
    timestamp = now.isoformat().replace("+00:00", "Z")
    for item in features:
        if not isinstance(item, dict):
            continue
        identifier = event_id(item)
        active.add(identifier)
        record = known.get(identifier, {
            "event_id": identifier, "first_seen_utc": timestamp,
            "source": "city_flood_alerts", "feature": item
        })
        record["last_seen_utc"] = timestamp
        record["feature"] = item
        record["active_at_last_poll"] = True
        known[identifier] = record
    for identifier, record in known.items():
        if identifier not in active:
            record["active_at_last_poll"] = False
    output = {
        "date": date, "source_url": URL, "last_success_utc": timestamp,
        "active_count": len(active), "alert_count": len(known),
        "alerts": sorted(known.values(), key=lambda a: a["first_seen_utc"], reverse=True)
    }
    # Avoid needless new commits on each empty polling run.
    if (not path.exists()) or known or previous.get("active_count"):
        if output != previous:
            path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(f"City flood alerts: {len(active)} active, {len(known)} archived on {date}")
    return output


if __name__ == "__main__":
    run()
