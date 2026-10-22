import multiprocessing
import os
import tempfile
import time
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
        self.assertEqual(load_settings("kazu"), plans_store.DEFAULT_SETTINGS)
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

    def test_results_finished_at_the_same_time_are_all_kept(self):
        # 予約可能日時が重なり、別々のプロセスの自動予約が同時に結果を書いても、どれも消えない
        ids = [f"p{i}" for i in range(8)]
        save_plans([plan(pid, "2026-10-26", 30, STATUS_PLANNED) for pid in ids])
        ctx = multiprocessing.get_context("spawn")
        procs = [ctx.Process(target=_finish_in_child, args=(str(plans_store.DATA_FILE), pid)) for pid in ids]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(60)
            self.assertEqual(proc.exitcode, 0)
        saved = {p["id"]: p for p in load_plans()}
        for pid in ids:
            self.assertEqual(saved[pid]["status"], STATUS_BOOKED)
            self.assertIn("last_run", saved[pid])
        self.assertFalse(plans_store._lock_file().exists())

    def test_stale_lock_is_removed(self):
        save_plans([plan("x", "2026-10-26", 30, STATUS_PLANNED)])
        lock = plans_store._lock_file()
        lock.touch()
        old = time.time() - plans_store.LOCK_STALE_SECONDS - 5
        os.utime(lock, (old, old))
        mark_booked("x", "E320", "auto")
        self.assertEqual(load_plans()[0]["status"], STATUS_BOOKED)


def _finish_in_child(data_file: str, plan_id: str) -> None:
    plans_store.DATA_FILE = Path(data_file)
    for _ in range(5):  # 何度も書いて、重なる機会を増やす
        record_run(plan_id, datetime(2026, 10, 19, 13, 0, 2), "空きなし", [])
    mark_booked(plan_id, "E320", "auto")


if __name__ == "__main__":
    unittest.main()
