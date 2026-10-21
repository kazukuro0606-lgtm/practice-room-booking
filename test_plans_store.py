import tempfile
import unittest
from datetime import date
from pathlib import Path

import plans_store
from plans_store import STATUS_BOOKED, STATUS_PLANNED, booked_minutes_on, load_plans, mark_booked, save_plans


def plan(pid, use_date, minutes, status):
    return {"id": pid, "use_date": use_date, "duration_min": minutes, "status": status}


class PlansStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        plans_store.DATA_FILE = Path(self.tmp.name) / "data" / "plans.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_booked_minutes_counts_only_booked_on_same_day(self):
        plans = [
            plan("a", "2026-10-26", 90, STATUS_BOOKED),
            plan("b", "2026-10-26", 60, STATUS_PLANNED),
            plan("c", "2026-10-27", 120, STATUS_BOOKED),
            plan("d", "2026-10-26", 30, STATUS_BOOKED),
        ]
        self.assertEqual(booked_minutes_on(plans, date(2026, 10, 26)), 120)
        self.assertEqual(booked_minutes_on(plans, date(2026, 10, 26), exclude_id="d"), 90)

    def test_mark_booked_and_old_plans_get_ids(self):
        save_plans([{"use_date": "2026-10-26", "duration_min": 90, "status": "予約完了（大学サイトで手動予約済み）"},
                    plan("x", "2026-10-26", 60, STATUS_PLANNED)])
        plans = load_plans()
        self.assertTrue(plans[0]["id"])
        self.assertEqual(load_plans()[0]["id"], plans[0]["id"])  # 読み直しても番号が変わらない
        self.assertEqual(plans[0]["status"], STATUS_BOOKED)
        mark_booked("x", "E320", "自動")
        saved = {p["id"]: p for p in load_plans()}
        self.assertEqual(saved["x"]["status"], STATUS_BOOKED)
        self.assertEqual(saved["x"]["booked_room"], "E320")


if __name__ == "__main__":
    unittest.main()
