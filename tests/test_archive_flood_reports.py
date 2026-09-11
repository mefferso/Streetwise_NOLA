import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import archive_flood_reports as archive


class ArchiveFloodReportsTests(unittest.TestCase):
    def test_rainwater_source_and_layers(self):
        self.assertIn("/Rainwater/Flooding/MapServer", archive.SERVICE_URL)
        self.assertEqual((archive.LIVE_LAYER_ID, archive.RECENT_LAYER_ID, archive.HISTORIC_LAYER_ID), (1, 2, 3))

    def test_timecreate_preserves_new_orleans_wall_clock(self):
        shaped_epoch = int(datetime(2026, 9, 4, 9, 35, 3, tzinfo=timezone.utc).timestamp() * 1000)
        parsed = archive.event_datetime({"TimeCreate": shaped_epoch})
        self.assertEqual(parsed.isoformat(), "2026-09-04T09:35:03-05:00")

    def test_timecreateutc_is_converted_from_true_utc(self):
        utc_epoch = int(datetime(2026, 9, 4, 14, 35, 3, tzinfo=timezone.utc).timestamp() * 1000)
        parsed = archive.event_datetime({"TimeCreateUTC": utc_epoch})
        self.assertEqual(parsed.isoformat(), "2026-09-04T09:35:03-05:00")

    def test_history_row_derives_true_utc_without_shifting_local_clock(self):
        shaped_epoch = int(datetime(2026, 9, 4, 9, 35, 3, tzinfo=timezone.utc).timestamp() * 1000)
        report = archive.normalize_feature(
            {
                "attributes": {"Incident": "003630", "TimeCreate": shaped_epoch},
                "geometry": {"x": -90.08, "y": 29.97},
            },
            archive.HISTORIC_LAYER_ID,
        )
        expected_utc = int(datetime(2026, 9, 4, 14, 35, 3, tzinfo=timezone.utc).timestamp() * 1000)
        self.assertEqual(report["time_create"], shaped_epoch)
        self.assertEqual(report["time_create_utc"], expected_utc)

    def test_date_qualified_incident_id_avoids_cross_year_collision(self):
        attrs = {"Incident": "003630"}
        first = archive.stable_event_id(attrs, None, datetime(2025, 9, 4, tzinfo=archive.LOCAL_ZONE))
        second = archive.stable_event_id(attrs, None, datetime(2026, 9, 4, tzinfo=archive.LOCAL_ZONE))
        self.assertNotEqual(first, second)
        self.assertEqual(second, "incident-20260904-003630")

    def test_historic_sync_runs_when_source_changes(self):
        original = archive.HISTORIC_STATE_PATH
        try:
            archive.HISTORIC_STATE_PATH = Path("does-not-exist.json")
            self.assertTrue(archive.historic_sync_due(datetime.now(timezone.utc)))
        finally:
            archive.HISTORIC_STATE_PATH = original


if __name__ == "__main__":
    unittest.main()
