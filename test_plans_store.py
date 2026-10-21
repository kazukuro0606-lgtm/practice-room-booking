import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import plans_store
from plans_store import (
    STATUS_BOOKED,
    STATUS_PLANNED,
    booked_minutes_on,
    claim_legacy,
    delete_user_data,
    load_plans,
    plans_of,
    load_settings,
    mark_booked,
    record_run,
    save_plans,
    save_settings,
)


def plan(pid, use_date, minutes, status):
    return {"id": pid, "use_date": use_date, "duration_min": minutes, "status": status}


class PlansStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        plans_store.DATA_FILE = Path(self.tmp.name) / "data" / "plans.json"
        plans_store.SETTINGS_DIR = Path(self.tmp.name) / "data" / "settings"
        plans_store.LEGACY_SETTINGS_FILE = Path(self.tmp.name) / "data" / "settings.json"

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

    def test_record_run_and_settings(self):
        save_plans([plan("x", "2026-10-26", 60, STATUS_PLANNED)])
        record_run("x", datetime(2026, 10, 19, 18, 0, 2), "空きなし", ["E320", "E321"])
        record_run("deleted", datetime(2026, 10, 19, 18, 0, 2), "空きなし", [])  # 消えた予定は無視
        run = load_plans()[0]["last_run"]
        self.assertEqual(run["full_rooms"], ["E320", "E321"])
        self.assertEqual(run["at"], "2026-10-19 18:00:02")
        self.assertEqual(load_settings("kazu"), {"favorite_rooms": [], "skip_confirm": False})
        save_settings("kazu", {"favorite_rooms": ["E330"], "skip_confirm": True})
        self.assertEqual(load_settings("kazu")["favorite_rooms"], ["E330"])
        self.assertEqual(load_settings("friend1")["favorite_rooms"], [])  # 人ごとに別

    def test_owner_separation_and_legacy_claim(self):
        plans_store.LEGACY_SETTINGS_FILE.parent.mkdir(parents=True)
        plans_store.LEGACY_SETTINGS_FILE.write_text('{"favorite_rooms": ["E325"], "skip_confirm": true}', encoding="utf-8")
        save_plans([plan("old", "2026-10-26", 90, STATUS_BOOKED)])
        claim_legacy("kazu")
        self.assertEqual(load_plans()[0]["owner"], "kazu")
        self.assertEqual(load_settings("kazu")["favorite_rooms"], ["E325"])

        save_plans(load_plans() + [{**plan("f1", "2026-10-26", 60, STATUS_BOOKED), "owner": "friend1"}])
        plans = load_plans()
        self.assertEqual([p["id"] for p in plans_of(plans, "friend1")], ["f1"])
        self.assertEqual(booked_minutes_on(plans, date(2026, 10, 26), owner="kazu"), 90)
        self.assertEqual(booked_minutes_on(plans, date(2026, 10, 26), owner="friend1"), 60)

        delete_user_data("friend1")
        self.assertEqual([p["id"] for p in load_plans()], ["old"])


if __name__ == "__main__":
    unittest.main()
