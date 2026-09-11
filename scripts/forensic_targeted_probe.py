#!/usr/bin/env python3
"""Fast, read-only probe of the strongest Streetwise recovery candidates."""

from __future__ import annotations

import concurrent.futures
import json
import re
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CTX = ssl._create_unverified_context()
HEADERS = {"User-Agent": "Streetwise-NOLA-Targeted-Forensics/1.0"}
CUTOFF = "2026-07-12 00:00:00"
ROOTS = [
    "https://gis.nola.gov/arcgis/rest/services",
    "https://maps.nola.gov/server/rest/services",
    "https://eocgis.nola.gov:6443/arcgis/rest/services",
    "https://eocgis.nola.gov/arcgis/rest/services",
    "https://eocgis.nola.gov/server/rest/services",
]
EXPLICIT = [
    "https://gis.nola.gov/arcgis/rest/services/Staging/Flood_Events/MapServer",
    "https://gis.nola.gov/arcgis/rest/services/Staging/Flood_Events/FeatureServer",
    "https://gis.nola.gov/arcgis/rest/services/Flood_Events/MapServer",
    "https://gis.nola.gov/arcgis/rest/services/Flood_Events/FeatureServer",
    "https://gis.nola.gov/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer",
    "https://gis.nola.gov/arcgis/rest/services/Streetwise/Streetwise_Live/FeatureServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/FeatureServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Traffic_Inc_21_UPASS/MapServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Traffic_Inc_21_UPASS/FeatureServer",
    "https://eocgis.nola.gov/server/rest/services/All_Flooding_as_20240201/MapServer",
    "https://eocgis.nola.gov/server/rest/services/All_Flooding_as_20240201/FeatureServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/Flooding/MapServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/Flooding/FeatureServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/COP/Underpass_WaterLevel/MapServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/COP/Underpass_WaterLevel/FeatureServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/ContrailOutput/MapServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/ContrailOutput/FeatureServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/FWS_WaterLevel/MapServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/FWS_WaterLevel/FeatureServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/HYFI/MapServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/HYFI/FeatureServer",
    "https://gis.nola.gov/arcgis/rest/services/apps/Open311Cases/MapServer",
    "https://gis.nola.gov/arcgis/rest/services/apps/Open311Cases/FeatureServer",
    "https://gis.nola.gov/arcgis/rest/services/Infrastructure/Open311Cases/MapServer",
    "https://gis.nola.gov/arcgis/rest/services/Infrastructure/Open311Cases/FeatureServer",
    "https://gis.nola.gov/arcgis/rest/services/PublicSafety/PondingAreas/MapServer",
    "https://gis.nola.gov/arcgis/rest/services/PublicSafety/PondingAreas/FeatureServer",
    "https://maps.nola.gov/server/rest/services/OpenGov/OpenGov_Requests/MapServer",
    "https://maps.nola.gov/server/rest/services/OpenGov/OpenGov_Requests/FeatureServer",
    "https://maps.nola.gov/server/rest/services/OpenGov/OpenGov_Tasks_Public/MapServer",
    "https://maps.nola.gov/server/rest/services/OpenGov/OpenGov_Tasks_Public/FeatureServer",
    "https://utility.arcgis.com/usrsvcs/servers/74697a2718c34ed999afe232d4e85fb1/rest/services/COP/ActiveCAD/MapServer",
    "https://utility.arcgis.com/usrsvcs/servers/74697a2718c34ed999afe232d4e85fb1/rest/services/COP/ActiveCAD/FeatureServer",
]
ITEMS = [
    "4c54b790fe444cc9bc16aec9ce30abc4",  # Streetwise application
    "c2947fd4c7f944799b9451e0ede938a7",  # NOHSEP dashboard
    "4716022e0e4b49a39652f96e6b32efe2",  # dashboard web map (private at last check)
    "74697a2718c34ed999afe232d4e85fb1",  # ActiveCAD proxy
    "12c4bf4823684f09a77c136f89e71924",  # Flood_Reports_2024 web map
    "3bd4994a26ac46a4b78088dd5ff498e7",  # PWD flooding tracker web map
    "509b677d7e294993858b9495d200fc0b",  # drainage application
    "8822671dc20d4e169a9e76e83ad3b842",  # Open311 item
]
KEYWORDS = re.compile(r"streetwise|flood|pond|rainwater|water.?level|underpass|high.?water|21f|311|cad|incident|drain|closure|request|public.?safety|emergency", re.I)


def get(url: str, params: dict | None = None, timeout: int = 18) -> dict:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    row = {"url": url}
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as response:
            raw = response.read()
            row.update({"ok": True, "status": response.status, "final_url": response.geturl(), "bytes": len(raw)})
        data = json.loads(raw.decode("utf-8-sig"))
        row["data"] = data
        if isinstance(data, dict) and data.get("error"):
            row["ok"] = False
            row["arcgis_error"] = data["error"]
    except Exception as exc:
        row.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return row


def catalog(root: str) -> dict:
    queue, seen, folders, services = [""], set(), [], []
    while queue:
        folder = queue.pop(0)
        if folder in seen:
            continue
        seen.add(folder)
        url = root + (("/" + urllib.parse.quote(folder, safe="/")) if folder else "")
        response = get(url, {"f": "json"})
        data = response.get("data") or {}
        folders.append({"folder": folder or "/", "request": {k: response.get(k) for k in ("url", "ok", "status", "error", "arcgis_error") if response.get(k) is not None}})
        for child in data.get("folders") or []:
            child = child if "/" in str(child) or not folder else f"{folder}/{child}"
            queue.append(child)
        for service in data.get("services") or []:
            name = str(service.get("name") or "")
            if folder and "/" not in name:
                name = f"{folder}/{name}"
            service["url"] = root + "/" + name + "/" + str(service.get("type"))
            services.append(service)
    return {"root": root, "folders": folders, "services": services,
            "keyword_services": [s for s in services if KEYWORDS.search(json.dumps(s))]}


def query(layer_url: str, **params) -> dict:
    base = {"f": "json", "where": "1=1", "returnGeometry": "false"}
    base.update(params)
    return get(layer_url.rstrip("/") + "/query", base)


def probe_layer(url: str, layer: dict, kind: str) -> dict:
    layer_url = f"{url}/{layer['id']}"
    meta_response = get(layer_url, {"f": "json"})
    meta = meta_response.get("data") or {}
    fields = meta.get("fields") or []
    dates = [f.get("name") for f in fields if f.get("type") == "esriFieldTypeDate"]
    strings = [f.get("name") for f in fields if f.get("type") == "esriFieldTypeString"]
    probes = {
        "count": query(layer_url, returnCountOnly="true"),
        "ids": query(layer_url, returnIdsOnly="true"),
        "last_rows": query(layer_url, outFields="*", orderByFields=f"{meta.get('objectIdField') or 'OBJECTID'} DESC", resultRecordCount=5),
    }
    for field in dates:
        stats = json.dumps([
            {"statisticType": "min", "onStatisticField": field, "outStatisticFieldName": "min_value"},
            {"statisticType": "max", "onStatisticField": field, "outStatisticFieldName": "max_value"},
        ])
        probes[f"date:{field}"] = {
            "stats": query(layer_url, outStatistics=stats),
            "cutoff_count": query(layer_url, where=f"{field} >= timestamp '{CUTOFF}'", returnCountOnly="true"),
            "newest": query(layer_url, where=f"{field} IS NOT NULL", outFields="*", orderByFields=f"{field} DESC", resultRecordCount=3),
        }
    for field in strings:
        if re.search(r"type|comment|description|category|request|incident|event|status", field, re.I):
            probes[f"text:{field}"] = {
                "21f": query(layer_url, where=f"UPPER({field}) LIKE '%21F%'", returnCountOnly="true"),
                "flood": query(layer_url, where=f"UPPER({field}) LIKE '%FLOOD%'", returnCountOnly="true"),
                "high_water": query(layer_url, where=f"UPPER({field}) LIKE '%HIGH WATER%'", returnCountOnly="true"),
            }
    return {"url": layer_url, "kind": kind, "metadata": meta_response, "probes": probes}


def probe_service(url: str) -> dict:
    response = get(url, {"f": "json"})
    data = response.get("data") or {}
    result = {"url": url, "metadata": response, "layers": []}
    jobs = [(url, x, "layer") for x in data.get("layers") or []] + [(url, x, "table") for x in data.get("tables") or []]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        result["layers"] = list(pool.map(lambda args: probe_layer(*args), jobs))
    return result


def item(item_id: str) -> dict:
    base = f"https://www.arcgis.com/sharing/rest/content/items/{item_id}"
    return {"id": item_id, "metadata": get(base, {"f": "json"}), "data": get(base + "/data", {"f": "json"}),
            "related_forward": get(base + "/relatedItems", {"f": "json", "relationshipType": "Service2Data", "direction": "forward"}),
            "related_reverse": get(base + "/relatedItems", {"f": "json", "relationshipType": "Service2Data", "direction": "reverse"})}


def main() -> None:
    report = {"generated_utc": datetime.now(timezone.utc).isoformat(), "cutoff": CUTOFF}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        catalogs = list(pool.map(catalog, ROOTS))
    report["catalogs"] = catalogs
    discovered = []
    for cat in catalogs:
        discovered.extend(s["url"] for s in cat["keyword_services"])
    service_urls = list(dict.fromkeys(EXPLICIT + discovered))
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        report["services"] = list(pool.map(probe_service, service_urls))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        report["items"] = list(pool.map(item, ITEMS))
    searches = []
    for phrase in ["Streetwise", '"Flood Events" New Orleans', '"Flooded Streets" New Orleans', '"All_Flooding"', '"ActiveCAD"', '"eocgis.nola.gov"', '"streetwise.nola.gov"', 'orgid:VhMjCzR3cIjEkh7L flood']:
        searches.append({"q": phrase, "response": get("https://www.arcgis.com/sharing/rest/search", {"f": "json", "q": phrase, "num": 100})})
    report["searches"] = searches
    out = Path("forensics/targeted_probe.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(out), "services": len(service_urls), "items": len(ITEMS)}, indent=2))


if __name__ == "__main__":
    main()
