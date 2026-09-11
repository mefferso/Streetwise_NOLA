#!/usr/bin/env python3
"""Read-only forensic inventory of public New Orleans flood and Streetwise data.

This diagnostic intentionally lives on a temporary branch.  It inventories ArcGIS
Server directories, interrogates candidate layers and tables, inspects Streetwise
web assets, and searches ArcGIS Online and Socrata catalogs.  It never edits a
remote service.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html.parser
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


USER_AGENT = "Streetwise-NOLA-Forensics/1.0"
TLS_CONTEXT = ssl._create_unverified_context()
TIMEOUT = 35
JULY_12 = "2026-07-12 00:00:00"

KEYWORDS = (
    "streetwise", "flood", "flooding", "high water", "highwater", "21f",
    "311", "emergency", "road closure", "road closures", "roadway incident",
    "incident", "drainage", "public safety", "publicsafety", "police", "cad",
    "real time crime", "rtcc", "traffic event", "traffic incident", "stormwater",
)

SERVICE_ROOTS = (
    "https://gis.nola.gov/arcgis/rest/services",
    "https://eocgis.nola.gov:6443/arcgis/rest/services",
    "https://eocgis.nola.gov/arcgis/rest/services",
)

KNOWN_SERVICE_URLS = (
    "https://gis.nola.gov/arcgis/rest/services/Staging/Flood_Events/MapServer",
    "https://gis.nola.gov/arcgis/rest/services/Staging/Flood_Events/FeatureServer",
    "https://gis.nola.gov/arcgis/rest/services/Flood_Events/MapServer",
    "https://gis.nola.gov/arcgis/rest/services/Flood_Events/FeatureServer",
    "https://gis.nola.gov/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer",
    "https://gis.nola.gov/arcgis/rest/services/Streetwise/Streetwise_Live/FeatureServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer",
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/FeatureServer",
)


def request_bytes(url: str, *, timeout: int = TIMEOUT) -> tuple[bytes | None, dict[str, Any]]:
    started = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    evidence: dict[str, Any] = {"url": url}
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=TLS_CONTEXT) as response:
            body = response.read()
            evidence.update({
                "ok": True,
                "status": getattr(response, "status", 200),
                "final_url": response.geturl(),
                "content_type": response.headers.get("Content-Type"),
                "bytes": len(body),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            })
            return body, evidence
    except Exception as exc:
        evidence.update({
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        })
        return None, evidence


def get_json(url: str, params: dict[str, Any] | None = None) -> tuple[Any, dict[str, Any]]:
    if params:
        separator = "&" if "?" in url else "?"
        url = url + separator + urllib.parse.urlencode(params, doseq=True)
    body, evidence = request_bytes(url)
    if body is None:
        return None, evidence
    try:
        data = json.loads(body.decode("utf-8-sig"))
    except Exception as exc:
        evidence.update({"ok": False, "json_error": str(exc), "sample": body[:500].decode("utf-8", "replace")})
        return None, evidence
    if isinstance(data, dict) and data.get("error"):
        evidence.update({"ok": False, "arcgis_error": data.get("error")})
    return data, evidence


def compact_error(evidence: dict[str, Any]) -> dict[str, Any]:
    keep = ("url", "ok", "status", "final_url", "content_type", "bytes", "elapsed_seconds", "error_type", "error", "json_error", "arcgis_error", "sample")
    return {key: evidence.get(key) for key in keep if key in evidence}


def text_blob(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False).lower()
    except Exception:
        return str(value).lower()


def keyword_hits(value: Any) -> list[str]:
    blob = text_blob(value)
    return [word for word in KEYWORDS if word in blob]


def service_url(root: str, name: str, service_type: str) -> str:
    escaped = "/".join(urllib.parse.quote(part, safe="") for part in name.split("/"))
    return f"{root}/{escaped}/{service_type}"


def crawl_service_root(root: str) -> dict[str, Any]:
    queue = [""]
    seen: set[str] = set()
    folders: list[dict[str, Any]] = []
    services: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    while queue:
        folder = queue.pop(0)
        if folder in seen:
            continue
        seen.add(folder)
        suffix = "/" + "/".join(urllib.parse.quote(part, safe="") for part in folder.split("/")) if folder else ""
        data, evidence = get_json(root + suffix, {"f": "pjson"})
        folders.append({"folder": folder or "/", "request": compact_error(evidence)})
        if not isinstance(data, dict):
            errors.append(compact_error(evidence))
            continue
        for child in data.get("folders") or []:
            child_path = child if "/" in str(child) or not folder else f"{folder}/{child}"
            if child_path not in seen:
                queue.append(child_path)
        for service in data.get("services") or []:
            name = str(service.get("name") or "")
            if folder and "/" not in name:
                name = f"{folder}/{name}"
            item = {
                "root": root,
                "folder": folder or None,
                "name": name,
                "type": service.get("type"),
            }
            item["url"] = service_url(root, name, str(service.get("type")))
            services.append(item)
    unique = {item["url"]: item for item in services}
    return {"root": root, "folders": folders, "services": list(unique.values()), "errors": errors}


def summarize_service_metadata(url: str, data: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": url,
        "request": compact_error(evidence),
        "name": data.get("mapName") or data.get("name"),
        "description": data.get("description"),
        "service_description": data.get("serviceDescription"),
        "capabilities": data.get("capabilities"),
        "supported_query_formats": data.get("supportedQueryFormats"),
        "max_record_count": data.get("maxRecordCount"),
        "has_versioned_data": data.get("hasVersionedData"),
        "supports_disconnected_editing": data.get("supportsDisconnectedEditing"),
        "sync_enabled": data.get("syncEnabled"),
        "current_version": data.get("currentVersion"),
        "layers": data.get("layers") or [],
        "tables": data.get("tables") or [],
        "document_info": data.get("documentInfo"),
        "units": data.get("units"),
        "initial_extent": data.get("initialExtent"),
        "full_extent": data.get("fullExtent"),
        "supported_extensions": data.get("supportedExtensions"),
    }


def inspect_service(item: dict[str, Any]) -> dict[str, Any]:
    data, evidence = get_json(item["url"], {"f": "pjson"})
    if not isinstance(data, dict):
        return {**item, "request": compact_error(evidence), "keyword_hits": keyword_hits(item)}
    summary = summarize_service_metadata(item["url"], data, evidence)
    summary.update({"root": item.get("root"), "folder": item.get("folder"), "catalog_name": item.get("name"), "type": item.get("type")})
    summary["keyword_hits"] = keyword_hits({"item": item, "metadata": summary})
    return summary


def layer_kind_url(service: dict[str, Any], layer: dict[str, Any], kind: str) -> str:
    return f"{service['url'].rstrip('/')}/{layer['id']}"


def layer_metadata_summary(url: str, data: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    fields = data.get("fields") or []
    return {
        "url": url,
        "request": compact_error(evidence),
        "id": data.get("id"),
        "name": data.get("name"),
        "type": data.get("type"),
        "description": data.get("description"),
        "display_field": data.get("displayField"),
        "geometry_type": data.get("geometryType"),
        "object_id_field": data.get("objectIdField") or next((f.get("name") for f in fields if f.get("type") == "esriFieldTypeOID"), None),
        "global_id_field": data.get("globalIdField"),
        "type_id_field": data.get("typeIdField"),
        "subtype_field": data.get("subtypeField") or data.get("subtypeFieldName"),
        "fields": fields,
        "types": data.get("types") or data.get("subtypes") or [],
        "templates": data.get("templates") or [],
        "capabilities": data.get("capabilities"),
        "max_record_count": data.get("maxRecordCount"),
        "supports_advanced_queries": data.get("supportsAdvancedQueries"),
        "advanced_query_capabilities": data.get("advancedQueryCapabilities"),
        "supported_query_formats": data.get("supportedQueryFormats"),
        "time_info": data.get("timeInfo"),
        "date_fields_time_reference": data.get("dateFieldsTimeReference"),
        "relationships": data.get("relationships") or [],
        "relationship_class_names": data.get("relationshipClassNames") or [],
        "has_attachments": data.get("hasAttachments"),
        "is_data_versioned": data.get("isDataVersioned"),
        "ownership_access_control": data.get("ownershipBasedAccessControlForFeatures"),
        "indexes": data.get("indexes"),
        "editing_info": data.get("editingInfo"),
        "source": data.get("source"),
        "parent_layer": data.get("parentLayer"),
        "sub_layers": data.get("subLayers") or [],
        "extent": data.get("extent"),
        "keyword_hits": keyword_hits(data),
    }


def query(url: str, **params: Any) -> dict[str, Any]:
    defaults = {"f": "json", "where": "1=1", "returnGeometry": "false"}
    defaults.update(params)
    data, evidence = get_json(url.rstrip("/") + "/query", defaults)
    return {"request": compact_error(evidence), "data": data}


def response_count(result: dict[str, Any]) -> int | None:
    data = result.get("data")
    if isinstance(data, dict):
        if isinstance(data.get("count"), int):
            return data["count"]
        if isinstance(data.get("features"), list):
            return len(data["features"])
        if isinstance(data.get("objectIds"), list):
            return len(data["objectIds"])
    return None


def safe_features(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data")
    return data.get("features") or [] if isinstance(data, dict) else []


def combine_where(parts: Iterable[str], operator: str = " OR ") -> str:
    values = [p for p in parts if p]
    return "(" + operator.join(values) + ")" if values else "1=0"


def inspect_layer(service: dict[str, Any], layer: dict[str, Any], kind: str) -> dict[str, Any]:
    url = layer_kind_url(service, layer, kind)
    data, evidence = get_json(url, {"f": "pjson"})
    if not isinstance(data, dict):
        return {"url": url, "service_url": service["url"], "kind": kind, "catalog_layer": layer, "request": compact_error(evidence)}

    result = layer_metadata_summary(url, data, evidence)
    result.update({"service_url": service["url"], "service_name": service.get("catalog_name"), "kind": kind})
    fields = data.get("fields") or []
    oid = result.get("object_id_field")
    date_fields = [str(f.get("name")) for f in fields if f.get("type") == "esriFieldTypeDate"]
    string_fields = [str(f.get("name")) for f in fields if f.get("type") == "esriFieldTypeString"]
    relevant_strings = [name for name in string_fields if any(token in name.lower() for token in ("comment", "type", "description", "category", "status", "incident", "event", "title", "name", "address", "request", "subject", "reason"))]

    probes: dict[str, Any] = {}
    probes["count_where_1_1"] = query(url, returnCountOnly="true")
    probes["ids_where_1_1"] = query(url, returnIdsOnly="true")
    probes["first_page"] = query(url, outFields="*", resultRecordCount=5, resultOffset=0)
    if oid:
        probes["lowest_object_ids"] = query(url, outFields="*", orderByFields=f"{oid} ASC", resultRecordCount=5)
        probes["highest_object_ids"] = query(url, outFields="*", orderByFields=f"{oid} DESC", resultRecordCount=10)
        ids_data = probes["ids_where_1_1"].get("data")
        ids = ids_data.get("objectIds") if isinstance(ids_data, dict) else None
        if isinstance(ids, list) and ids:
            probes["object_id_range"] = {"min": min(ids), "max": max(ids), "count": len(ids), "sample_tail": sorted(ids)[-20:]}

    date_summary: dict[str, Any] = {}
    for field in date_fields:
        stat_defs = json.dumps([
            {"statisticType": "min", "onStatisticField": field, "outStatisticFieldName": "min_value"},
            {"statisticType": "max", "onStatisticField": field, "outStatisticFieldName": "max_value"},
            {"statisticType": "count", "onStatisticField": field, "outStatisticFieldName": "nonnull_count"},
        ])
        stats = query(url, outStatistics=stat_defs)
        recent = query(url, where=f"{field} >= timestamp '{JULY_12}'", returnCountOnly="true")
        newest = query(url, outFields="*", where=f"{field} IS NOT NULL", orderByFields=f"{field} DESC", resultRecordCount=10)
        oldest = query(url, outFields="*", where=f"{field} IS NOT NULL", orderByFields=f"{field} ASC", resultRecordCount=3)
        date_summary[field] = {
            "statistics": stats,
            "july_12_or_newer": recent,
            "july_12_or_newer_count": response_count(recent),
            "newest_rows": newest,
            "oldest_rows": oldest,
        }
    probes["date_fields"] = date_summary

    text_tests: dict[str, Any] = {}
    for field in relevant_strings[:16]:
        clauses = {
            "contains_flood": f"UPPER({field}) LIKE '%FLOOD%'",
            "contains_21f": f"UPPER({field}) LIKE '%21F%'",
            "contains_high_water": f"UPPER({field}) LIKE '%HIGH WATER%'",
            "contains_july_12": f"{field} LIKE '%2026-07-12%'",
        }
        field_results: dict[str, Any] = {}
        for label, where in clauses.items():
            tested = query(url, where=where, returnCountOnly="true")
            count = response_count(tested)
            field_results[label] = {"where": where, "count": count, "request": tested.get("request")}
            if count:
                sample = query(url, where=where, outFields="*", resultRecordCount=10)
                field_results[label]["sample"] = sample
        text_tests[field] = field_results
    probes["text_fields"] = text_tests

    any_date_recent = sum(v.get("july_12_or_newer_count") or 0 for v in date_summary.values())
    any_text_recent = sum((details.get("contains_july_12") or {}).get("count") or 0 for details in text_tests.values())
    result["probe_summary"] = {
        "total_count": response_count(probes["count_where_1_1"]),
        "date_fields": date_fields,
        "text_fields_tested": list(text_tests),
        "july_12_plus_date_match_sum": any_date_recent,
        "july_12_text_match_sum": any_text_recent,
    }
    result["probes"] = probes
    return result


class AssetParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for key in ("src", "href", "data-main"):
            value = values.get(key)
            if value:
                self.assets.append(value)


URL_RE = re.compile(r"https?://[^\"'<>\\\s]+", re.I)
SERVICE_RE = re.compile(r"(?:https?:)?//[^\"'<>\\\s]+/(?:MapServer|FeatureServer)(?:/\d+)?", re.I)
RELATIVE_SERVICE_RE = re.compile(r"[\"']([^\"']*(?:MapServer|FeatureServer)(?:/\d+)?[^\"']*)[\"']", re.I)
ITEM_ID_RE = re.compile(r"\b[0-9a-f]{32}\b", re.I)


def extract_references(text: str, base_url: str) -> dict[str, Any]:
    urls = sorted(set(URL_RE.findall(text)))
    services = sorted(set(SERVICE_RE.findall(text)))
    relatives = sorted(set(match.group(1) for match in RELATIVE_SERVICE_RE.finditer(text)))
    resolved = []
    for value in relatives:
        if len(value) < 500:
            resolved.append(urllib.parse.urljoin(base_url, value))
    snippets = []
    lowered = text.lower()
    for needle in ("mapserver", "featureserver", "streetwise", "flood", "21f", "arcgis", "eocgis", "gis.nola"):
        start = 0
        while len(snippets) < 200:
            pos = lowered.find(needle, start)
            if pos < 0:
                break
            snippets.append(text[max(0, pos - 180): min(len(text), pos + 360)].replace("\n", " "))
            start = pos + len(needle)
    return {
        "urls": urls,
        "service_urls": sorted(set(services + resolved)),
        "arcgis_item_ids": sorted(set(ITEM_ID_RE.findall(text))),
        "snippets": snippets,
    }


def inspect_streetwise() -> dict[str, Any]:
    start_url = "https://streetwise.nola.gov/"
    body, evidence = request_bytes(start_url)
    result: dict[str, Any] = {"root_request": compact_error(evidence), "assets": []}
    if body is None:
        return result
    source = body.decode("utf-8", "replace")
    result["html_sha256"] = hashlib.sha256(body).hexdigest()
    result["html_references"] = extract_references(source, evidence.get("final_url") or start_url)
    parser = AssetParser()
    parser.feed(source)
    assets = [urllib.parse.urljoin(evidence.get("final_url") or start_url, asset) for asset in parser.assets]
    common = [
        "config.json", "appConfig.json", "js/config.json", "assets/config.json",
        "manifest.json", "sharing/rest", "robots.txt", "sitemap.xml",
    ]
    assets.extend(urllib.parse.urljoin(start_url, value) for value in common)
    seen: set[str] = set()
    for asset in assets:
        if asset in seen or len(seen) >= 150:
            continue
        seen.add(asset)
        parsed = urllib.parse.urlparse(asset)
        if parsed.netloc not in {"streetwise.nola.gov", "www.streetwise.nola.gov"} and not any(token in asset.lower() for token in (".js", "config.json")):
            continue
        asset_body, asset_evidence = request_bytes(asset)
        record: dict[str, Any] = {"request": compact_error(asset_evidence)}
        if asset_body is not None and len(asset_body) <= 25_000_000:
            text = asset_body.decode("utf-8", "replace")
            record["sha256"] = hashlib.sha256(asset_body).hexdigest()
            record["references"] = extract_references(text, asset_evidence.get("final_url") or asset)
        result["assets"].append(record)
    return result


def arcgis_online_search(query_text: str, max_results: int = 300) -> dict[str, Any]:
    base = "https://www.arcgis.com/sharing/rest/search"
    start = 1
    rows: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    while len(rows) < max_results:
        data, evidence = get_json(base, {"f": "json", "q": query_text, "num": 100, "start": start})
        requests.append(compact_error(evidence))
        if not isinstance(data, dict):
            break
        rows.extend(data.get("results") or [])
        next_start = int(data.get("nextStart") or -1)
        if next_start <= 0:
            break
        start = next_start
    return {"query": query_text, "requests": requests, "results": rows[:max_results]}


def inspect_arcgis_item(item: dict[str, Any]) -> dict[str, Any]:
    item_id = item.get("id")
    base = f"https://www.arcgis.com/sharing/rest/content/items/{item_id}"
    metadata, metadata_evidence = get_json(base, {"f": "json"})
    data, data_evidence = get_json(base + "/data", {"f": "json"})
    combined = {"search_result": item, "metadata": metadata, "data": data}
    return {
        "id": item_id,
        "metadata_request": compact_error(metadata_evidence),
        "data_request": compact_error(data_evidence),
        "title": item.get("title"),
        "owner": item.get("owner"),
        "type": item.get("type"),
        "url": item.get("url"),
        "modified": item.get("modified"),
        "tags": item.get("tags"),
        "description": item.get("description"),
        "snippet": item.get("snippet"),
        "access": item.get("access"),
        "references": extract_references(json.dumps(combined, ensure_ascii=False), base),
        "metadata": metadata,
        "data": data,
    }


def inspect_socrata() -> list[dict[str, Any]]:
    output = []
    for term in ("New Orleans flood", "New Orleans high water", "New Orleans 311", "New Orleans road closure", "Streetwise NOLA"):
        url = "https://api.us.socrata.com/api/catalog/v1"
        data, evidence = get_json(url, {"q": term, "search_context": "data.nola.gov", "limit": 100})
        output.append({"query": term, "request": compact_error(evidence), "data": data})
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="forensics/arcgis_probe.json")
    args = parser.parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": {"cutoff": JULY_12, "keywords": KEYWORDS, "service_roots": SERVICE_ROOTS},
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        catalogs = list(pool.map(crawl_service_root, SERVICE_ROOTS))
    report["service_catalogs"] = catalogs

    catalog_items: dict[str, dict[str, Any]] = {}
    for catalog in catalogs:
        for item in catalog.get("services") or []:
            catalog_items[item["url"]] = item
    for url in KNOWN_SERVICE_URLS:
        service_type = "FeatureServer" if url.endswith("FeatureServer") else "MapServer"
        name = url.split("/services/", 1)[-1].rsplit("/", 1)[0]
        catalog_items.setdefault(url, {"url": url, "name": name, "type": service_type, "root": url.split("/services/", 1)[0] + "/services", "folder": name.rsplit("/", 1)[0] if "/" in name else None})

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        inspected_services = list(pool.map(inspect_service, catalog_items.values()))
    report["all_services"] = inspected_services

    candidates = [service for service in inspected_services if service.get("keyword_hits")]
    counterpart_items: dict[str, dict[str, Any]] = {}
    for service in candidates:
        url = service["url"]
        if url.endswith("/MapServer"):
            other = url[:-9] + "FeatureServer"
        elif url.endswith("/FeatureServer"):
            other = url[:-13] + "MapServer"
        else:
            continue
        if other not in catalog_items:
            counterpart_items[other] = {"url": other, "name": service.get("catalog_name"), "type": other.rsplit("/", 1)[-1], "root": service.get("root"), "folder": service.get("folder")}
    if counterpart_items:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            counterparts = list(pool.map(inspect_service, counterpart_items.values()))
        inspected_services.extend(counterparts)
        candidates.extend([item for item in counterparts if item.get("request", {}).get("ok") or item.get("keyword_hits")])
    report["candidate_services"] = candidates

    layer_jobs: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    seen_layer_urls: set[str] = set()
    for service in candidates:
        for kind, key in (("layer", "layers"), ("table", "tables")):
            for layer in service.get(key) or []:
                if layer.get("id") is None:
                    continue
                url = layer_kind_url(service, layer, kind)
                if url not in seen_layer_urls:
                    seen_layer_urls.add(url)
                    layer_jobs.append((service, layer, kind))

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        layer_results = list(pool.map(lambda values: inspect_layer(*values), layer_jobs))
    report["candidate_layers_and_tables"] = layer_results

    report["streetwise_web_application"] = inspect_streetwise()

    ago_queries = [
        'Streetwise',
        '"Flood Events" New Orleans',
        '"streetwise.nola.gov"',
        '"eocgis.nola.gov"',
        '"gis.nola.gov" flood',
        'New Orleans 21F',
        'New Orleans high water',
        'owner:nolagis flood',
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        searches = list(pool.map(arcgis_online_search, ago_queries))
    report["arcgis_online_searches"] = searches
    candidate_items: dict[str, dict[str, Any]] = {}
    for search in searches:
        for item in search.get("results") or []:
            if keyword_hits(item) or any(host in text_blob(item) for host in ("nola.gov", "eocgis", "streetwise")):
                candidate_items[str(item.get("id"))] = item
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        report["arcgis_online_candidate_items"] = list(pool.map(inspect_arcgis_item, candidate_items.values()))

    report["socrata_catalog_searches"] = inspect_socrata()

    output_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output_path),
        "service_count": len(inspected_services),
        "candidate_service_count": len(candidates),
        "candidate_layer_table_count": len(layer_results),
        "arcgis_online_item_count": len(candidate_items),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
