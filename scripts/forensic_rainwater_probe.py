#!/usr/bin/env python3
"""Read-only evidence summary for the discovered Rainwater/Flooding service."""

from __future__ import annotations

import collections
import json
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CTX = ssl._create_unverified_context()
BASES = [
    "https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/Flooding/MapServer",
    "https://eocgis.nola.gov/server/rest/services/Rainwater/Flooding/MapServer",
]
CUTOFF_MS = int(datetime(2026, 7, 12, tzinfo=timezone.utc).timestamp() * 1000)


def get(url: str, params: dict | None = None) -> dict:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Streetwise-NOLA-Rainwater-Forensics/1.0"})
        with urllib.request.urlopen(request, timeout=30, context=CTX) as response:
            data = json.load(response)
        return {"url": url, "ok": not bool(data.get("error")) if isinstance(data, dict) else True, "data": data}
    except Exception as exc:
        return {"url": url, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def query(base: str, layer: int, **params) -> dict:
    defaults = {"f": "json", "where": "1=1", "returnGeometry": "false"}
    defaults.update(params)
    return get(f"{base}/{layer}/query", defaults)


def features(response: dict) -> list[dict]:
    return [f.get("attributes") or {} for f in (response.get("data") or {}).get("features") or []]


def iso(ms) -> str | None:
    if not isinstance(ms, (int, float)):
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def fingerprint(a: dict) -> tuple:
    return tuple(a.get(k) for k in ("Incident", "TimeCreate", "Address", "Type", "MapX", "MapY"))


def summarize_layer(base: str, layer: int) -> dict:
    metadata = get(f"{base}/{layer}", {"f": "json"})
    count = query(base, layer, returnCountOnly="true")
    ids = query(base, layer, returnIdsOnly="true")
    pages, rows = [], []
    for offset in range(0, 7000, 1000):
        page = query(base, layer, outFields="*", resultOffset=offset, resultRecordCount=1000,
                     orderByFields="TimeCreate ASC")
        part = features(page)
        pages.append({"offset": offset, "returned": len(part), "exceededTransferLimit": (page.get("data") or {}).get("exceededTransferLimit"),
                      "ok": page.get("ok"), "error": page.get("error") or (page.get("data") or {}).get("error")})
        rows.extend(part)
        if len(part) < 1000:
            break
    recent = [a for a in rows if isinstance(a.get("TimeCreate"), (int, float)) and a["TimeCreate"] >= CUTOFF_MS]
    unique = {}
    for a in rows:
        unique.setdefault(fingerprint(a), a)
    unique_recent = {}
    for a in recent:
        unique_recent.setdefault(fingerprint(a), a)
    by_month = collections.Counter()
    for a in unique.values():
        stamp = iso(a.get("TimeCreate"))
        by_month[stamp[:7] if stamp else "null"] += 1
    id_values = (ids.get("data") or {}).get("objectIds") or []
    def clean(a: dict) -> dict:
        return {k: (iso(v) if k == "TimeCreate" else v) for k, v in a.items()}
    date_where = "TimeCreate >= timestamp '2026-07-12 00:00:00'"
    date_direct = query(base, layer, where=date_where, outFields="*", orderByFields="TimeCreate ASC", resultRecordCount=1000)
    return {
        "metadata": metadata,
        "count": count,
        "ids": {"request": ids, "returned": len(id_values), "unique": len(set(id_values)),
                "duplicates": len(id_values) - len(set(id_values)), "min": min(id_values) if id_values else None, "max": max(id_values) if id_values else None},
        "pages": pages,
        "rows_returned": len(rows),
        "unique_fingerprints": len(unique),
        "duplicate_fingerprints": len(rows) - len(unique),
        "oldest": clean(min(unique.values(), key=lambda a: a.get("TimeCreate") or 10**30)) if unique else None,
        "newest": clean(max(unique.values(), key=lambda a: a.get("TimeCreate") or -1)) if unique else None,
        "unique_by_month": dict(sorted(by_month.items())),
        "recent_rows": [clean(a) for a in recent],
        "recent_unique_rows": [clean(a) for a in unique_recent.values()],
        "recent_direct_query": date_direct,
        "where_variants": {
            "one_equals_one": count,
            "type_21f": query(base, layer, where="Type = '21F'", returnCountOnly="true"),
            "typetext_flood": query(base, layer, where="UPPER(TypeText) LIKE '%FLOOD%'", returnCountOnly="true"),
            "cutoff_timestamp": query(base, layer, where=date_where, returnCountOnly="true"),
            "cutoff_epoch": query(base, layer, where=f"TimeCreate >= {CUTOFF_MS}", returnCountOnly="true"),
        },
    }


def main() -> None:
    report = {"generated_utc": datetime.now(timezone.utc).isoformat(), "cutoff_ms": CUTOFF_MS, "services": {}}
    for base in BASES:
        report["services"][base] = {"metadata": get(base, {"f": "json"}),
                                     "layers": {str(i): summarize_layer(base, i) for i in (1, 2, 3)}}
    out = Path("forensics/rainwater_probe.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(out), "services": len(BASES)}, indent=2))


if __name__ == "__main__":
    main()
