import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("city_alerts", Path(__file__).resolve().parents[1] / "scripts" / "archive_city_alerts.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestCityAlertArchive(unittest.TestCase):
    def test_extract_and_reject_unknown_schema(self):
        self.assertEqual(module.extract({"features": []}), [])
        self.assertEqual(module.extract({"alerts": [{"id": 2}]}), [{"id": 2}])
        with self.assertRaises(ValueError):
            module.extract({"unexpected": []})

    def test_observations_are_not_mixed_with_21f_and_are_retained(self):
        t = datetime(2026, 10, 31, 16, 0, tzinfo=timezone.utc)
        feature = {"attributes": {"OBJECTID": 12, "Address": "CANAL UNDERPASS", "status": "CLOSED"}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = module.run(fetch=lambda: {"features": [feature]}, now=t, directory=root)
            self.assertEqual(first["active_count"], 1)
            self.assertEqual(first["alerts"][0]["feature"], feature)
            second = module.run(fetch=lambda: {"features": []}, now=t + timedelta(minutes=10), directory=root)
            self.assertEqual(second["active_count"], 0)
            self.assertEqual(second["alert_count"], 1)
            self.assertFalse(second["alerts"][0]["active_at_last_poll"])
            self.assertEqual(second["alerts"][0]["first_seen_utc"], first["alerts"][0]["first_seen_utc"])
            self.assertTrue((root / "2026-10-31.json").exists())


if __name__ == "__main__":
    unittest.main()
