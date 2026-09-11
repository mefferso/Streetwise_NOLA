#!/usr/bin/env python3
"""Forensic discovery of public New Orleans flood/Streetwise GIS sources.

Enumerates public ArcGIS Server services on the City's GIS hosts, inspects likely
flood/CAD/311/rain-related services, and records layer schemas plus date ranges
and post-2026-07-12 counts. This is diagnostic only; it does not alter archives.
"""

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CUTOFF = "2026-07-12 00:00:00"
HOSTS = [
    "https://gis.nola.gov/arcgis/rest/services",
    "https://eocgis.nola.gov:6443/arcgis/rest/services",
]
KEYWORDS = (
    "flood", "rain", "streetwise", "311", "hyfi", "water", "pond",
    "drain", "cad", "emergency", "publicsafety", "public_safety",
)
EXPLICIT_SERVICES = [
    "https://gis.nola.gov/arcgis/rest/services/Staging/Flood_Events/MapServer",
    "https://gis.nola.gov/arcgis/rest/services/dev/WhereYaFloodin/MapServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/Flooding/MapServer",
]
OUT = Path("data/discovery/flood_source_discovery.json")

ssl._create_default_https_context = ssl._create_unverified_context


def fetch_json(url: str, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "Streetwise-NOLA-Forensics/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(json.dumps(data["error"], sort_keys=True))
    return data


def pj(url: str) -> str:
    return url + ("&" if "?" in url else "?") + "f=pjson"


def list_services(root: str) -> tuple[list[str], list[dict[str, str]], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    services: list[dict[str, str]] = []
    folders_seen: list[str] = []
    try:
        top = fetch_json(pj(root))
    except Exception as exc:
        return folders_seen, services, [{"url": root, "error": str(exc)}]

    for svc in top.get("services") or []:
        services.append(svc)
    folders = top.get("folders") or []
    for folder in folders:
        folders_seen.append(folder)
        try:
            child = fetch_json(pj(f"{root}/{urllib.parse.quote(folder)}"))
            services.extend(child.get("services") or [])
        except Exception as exc:
            errors.append({"url": f"{root}/{folder}", "error": str(exc)})
    return folders_seen, services, errors


def service_url(root: str, svc: dict[str, str]) -> str:
    name = svc.get("name", "")
    typ = svc.get("type", "MapServer")
    return f"{root}/{name}/{typ}"


def relevant(name: str) -> bool:
    x = name.lower().replace(" ", "")
    return any(k in x for k in KEYWORDS)


def query_json(layer_url: str, params: dict[str, Any]) -> dict[str, Any]:
    return fetch_json(f"{layer_url}/query?{urllib.parse.urlencode(params)}")


def inspect_layer(layer_url: str, layer_meta: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "url": layer_url,
        "id": layer_meta.get("id"),
        "name": layer_meta.get("name"),
        "type": layer_meta.get("type"),
        "geometryType": layer_meta.get("geometryType"),
        "maxRecordCount": layer_meta.get("maxRecordCount"),
        "definitionExpression": layer_meta.get("definitionExpression"),
        "timeInfo": layer_meta.get("timeInfo"),
        "fields": [],
        "date_probes": [],
        "errors": [],
    }
    fields = layer_meta.get("fields") or []
    result["fields"] = [
        {"name": f.get("name"), "alias": f.get("alias"), "type": f.get("type")}
        for f in fields
    ]

    try:
        count = query_json(layer_url, {"f": "json", "where": "1=1", "returnCountOnly": "true"})
        result["total_count"] = count.get("count")
    except Exception as exc:
        result["errors"].append(f"count: {exc}")

    candidates = []
    for f in fields:
        name = str(f.get("name") or "")
        lower = name.lower()
        if f.get("type") == "esriFieldTypeDate" or any(t in lower for t in ("time", "date", "open", "close", "create", "update")):
            candidates.append(name)

    for field in candidates[:12]:
        probe: dict[str, Any] = {"field": field}
        try:
            stats = query_json(layer_url, {
                "f": "json", "where": "1=1", "returnGeometry": "false",
                "outStatistics": json.dumps([
                    {"statisticType": "min", "onStatisticField": field, "outStatisticFieldName": "minv"},
                    {"statisticType": "max", "onStatisticField": field, "outStatisticFieldName": "maxv"},
                ]),
            })
            feats = stats.get("features") or []
            if feats:
                probe["min"] = (feats[0].get("attributes") or {}).get("minv")
                probe["max"] = (feats[0].get("attributes") or {}).get("maxv")
        except Exception as exc:
            probe["stats_error"] = str(exc)

        # ArcGIS standardized SQL date syntax. Even string/numeric fields may fail;
        # retaining the error is useful forensic evidence.
        try:
            post = query_json(layer_url, {
                "f": "json",
                "where": f"{field} >= timestamp '{CUTOFF}'",
                "returnCountOnly": "true",
            })
            probe["post_cutoff_count"] = post.get("count")
        except Exception as exc:
            probe["post_cutoff_error"] = str(exc)

        if probe.get("post_cutoff_count"):
            try:
                sample = query_json(layer_url, {
                    "f": "json",
                    "where": f"{field} >= timestamp '{CUTOFF}'",
                    "outFields": "*",
                    "returnGeometry": "true",
                    "outSR": "4326",
                    "orderByFields": f"{field} DESC",
                    "resultRecordCount": "5",
                })
                probe["post_cutoff_sample"] = sample.get("features") or []
            except Exception as exc:
                probe["sample_error"] = str(exc)
        result["date_probes"].append(probe)
    return result


def inspect_service(url: str) -> dict[str, Any]:
    out: dict[str, Any] = {"url": url, "layers": [], "tables": [], "errors": []}
    try:
        meta = fetch_json(pj(url))
    except Exception as exc:
        out["errors"].append(f"service metadata: {exc}")
        return out
    out.update({
        "serviceDescription": meta.get("serviceDescription"),
        "mapName": meta.get("mapName"),
        "supportedQueryFormats": meta.get("supportedQueryFormats"),
    })
    entries = []
    for kind in ("layers", "tables"):
        for x in meta.get(kind) or []:
            entries.append((kind, x))
    for kind, entry in entries:
        lid = entry.get("id")
        try:
            lm = fetch_json(pj(f"{url}/{lid}"))
            inspected = inspect_layer(f"{url}/{lid}", lm)
        except Exception as exc:
            inspected = {"id": lid, "name": entry.get("name"), "errors": [str(exc)]}
        out[kind].append(inspected)
    return out


def main() -> int:
    run = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    discovered: dict[str, Any] = {"run_time_utc": run, "cutoff": CUTOFF, "hosts": [], "services": []}
    urls: set[str] = set(EXPLICIT_SERVICES)

    for root in HOSTS:
        folders, svcs, errors = list_services(root)
        relevant_svcs = [s for s in svcs if relevant(s.get("name", ""))]
        discovered["hosts"].append({
            "root": root,
            "folders": folders,
            "service_count": len(svcs),
            "relevant_services": relevant_svcs,
            "errors": errors,
        })
        for svc in relevant_svcs:
            urls.add(service_url(root, svc))

    # Probe FeatureServer siblings too; some ArcGIS publications expose richer
    # tables/features there even when the MapServer is the obvious public URL.
    expanded = set(urls)
    for url in list(urls):
        if url.endswith("/MapServer"):
            expanded.add(url[:-9] + "FeatureServer")

    for url in sorted(expanded):
        discovered["services"].append(inspect_service(url))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(discovered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}; inspected {len(expanded)} service endpoints")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
