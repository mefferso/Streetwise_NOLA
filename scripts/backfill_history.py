#!/usr/bin/env python3
"""One-shot historical backfill for Streetwise NOLA flood incidents.

Pull the City's Historic Flood Incidents layer and rebuild daily event catalogs
from 2026-07-12 forward. This is intentionally separate from the normal poller
so a missed-source period can be repaired immediately and repeatably.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from archive_flood_reports import (
    HISTORIC_LAYER_ID,
    EVENTS_DIR,
    LOCAL_ZONE,
    fetch_layer,
    normalize_feature,
    parse_local_datetime,
    merge_catalog_event,
    rebuild_index,
)

START_DATE = datetime(2026, 7, 12, tzinfo=LOCAL_ZONE)


def main() -> int:
    now = datetime.now(timezone.utc)
    run_iso = now.isoformat().replace('+00:00', 'Z')
    fallback_date = now.astimezone(LOCAL_ZONE).date().isoformat()

    EVENTS_DIR.mkdir(parents=True, exist_ok=True)

    features = fetch_layer(HISTORIC_LAYER_ID)
    reports = [normalize_feature(feature, HISTORIC_LAYER_ID) for feature in features]

    considered = 0
    skipped_old = 0
    skipped_no_time = 0
    changed_dates: set[str] = set()

    # Historical records are not current/active by definition for this repair.
    active_ids: set[str] = set()

    for report in reports:
        when = parse_local_datetime(report.get('event_time_local'))
        if when is None:
            skipped_no_time += 1
            continue
        if when < START_DATE:
            skipped_old += 1
            continue

        considered += 1
        date_value, changed = merge_catalog_event(
            report,
            run_iso=run_iso,
            active_ids=active_ids,
            fallback_date=fallback_date,
        )
        if changed:
            changed_dates.add(date_value)

    rebuild_index()

    summary = {
        'run_time_utc': run_iso,
        'source_layer': HISTORIC_LAYER_ID,
        'source_feature_count': len(features),
        'start_date_local': START_DATE.date().isoformat(),
        'records_backfilled_or_checked': considered,
        'records_skipped_before_start': skipped_old,
        'records_skipped_without_time': skipped_no_time,
        'dates_changed': sorted(changed_dates),
        'date_count_changed': len(changed_dates),
    }
    (EVENTS_DIR.parent / 'backfill_summary.json').write_text(
        json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8'
    )

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
