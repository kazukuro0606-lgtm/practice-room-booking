import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import account_checks
import plans_store
import scheduler
from booking_rules import TOKYO
from plans_store import AUTO_OFF, AUTO_QUEUED, AUTO_RUNNING, STATUS_BOOKED, STATUS_PLANNED, load_plans, save_plans


def plan(pid, auto, status=STATUS_PLANNED, use_date="2026-10-29", start="15:00", minutes=60):
    return {"id": pid, "owner": "kazu", "use_date": use_date, "start": start, "duration_min": minutes,
            "status": status, "auto": auto}


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        plans_store.DATA_FILE = Path(self.tmp.name) / "data" / "plans.json"
        plans_store.HEARTBEAT_FILE = Path(self.tmp.name) / "data" / "scheduler.json"
        account_checks.CHECK_DIR = Path(self.tmp.name) / "data" / "account_checks"
        self._users_to_check = scheduler.users_to_check
        scheduler.users_to_check = lambda: []

    def tearDown(self):
        scheduler.users_to_check = self._users_to_check
        self.tmp.cleanup()

    def test_opens_at(self):
        # 2026-10-29 15:00〜16:00 → 2026-10-22 16:00 から予約可能
        self.assertEqual(scheduler.opens_at(plan("a", AUTO_QUEUED)), datetime(2026, 10, 22, 16, 0, tzinfo=TOKYO))

    def test_due_only_queued_planned_and_within_10_minutes(self):
        plans = [
            plan("queued", AUTO_QUEUED),
            plan("off", AUTO_OFF),
            plan("running", AUTO_RUNNING),
            plan("booked", AUTO_QUEUED, status=STATUS_BOOKED),
            plan("later", AUTO_QUEUED, use_date="2026-10-30"),
        ]
        self.assertEqual(scheduler.due_plans(plans, datetime(2026, 10, 22, 15, 49, tzinfo=TOKYO)), [])
        due = scheduler.due_plans(plans, datetime(2026, 10, 22, 15, 50, tzinfo=TOKYO))
        self.assertEqual([p["id"] for p in due], ["queued"])
        # 予約可能日時を過ぎてから任された予定は、すぐ起動する（later も 10/23 16:00 に受付開始済み）
        due = scheduler.due_plans(plans, datetime(2026, 10, 25, 9, 0, tzinfo=TOKYO))
        self.assertEqual([p["id"] for p in due], ["queued", "later"])

    def test_tick_launches_once_and_marks_running(self):
        save_plans([plan("queued", AUTO_QUEUED)])
        launched = []

        class FakeProc:
            def poll(self):
                return None

        original = scheduler.launch
        scheduler.launch = lambda p: launched.append(p["id"]) or FakeProc()
        try:
            running = {}
            now = datetime(2026, 10, 22, 15, 55, tzinfo=TOKYO)
            scheduler.tick(now, running)
            scheduler.tick(now, running)  # 2回目は起動しない
        finally:
            scheduler.launch = original
        self.assertEqual(launched, ["queued"])
        self.assertEqual(load_plans()[0]["auto"], AUTO_RUNNING)
        self.assertEqual(plans_store.scheduler_last_seen(), now)

    def test_refuses_to_start_when_another_is_running(self):
        now = datetime(2026, 10, 22, 15, 0, 0, tzinfo=TOKYO)
        self.assertFalse(scheduler.already_running(now))  # 一度も動いていない
        plans_store.write_heartbeat(now)
        self.assertTrue(scheduler.already_running(now.replace(minute=1)))  # 1分前に動いている印
        self.assertFalse(scheduler.already_running(now.replace(minute=2)))  # 2分前なら止まっている

    def test_requeued_plan_waits_for_previous_run(self):
        save_plans([plan("p", AUTO_QUEUED)])  # 取り消し→任せ直しされた状態
        launched = []

        class Alive:
            def poll(self):
                return None

        original = scheduler.launch
        scheduler.launch = lambda p: launched.append(p["id"]) or Alive()
        try:
            running = {"p": Alive()}  # 前の自動予約がまだ動いている
            scheduler.tick(datetime(2026, 10, 22, 15, 55, tzinfo=TOKYO), running)
        finally:
            scheduler.launch = original
        self.assertEqual(launched, [])
        self.assertEqual(load_plans()[0]["auto"], AUTO_QUEUED)

    def test_account_checks_are_started_once(self):
        launched = []

        class Alive:
            def poll(self):
                return None

        scheduler.users_to_check = lambda: ["friend1"]
        original = scheduler.launch_check
        scheduler.launch_check = lambda u: launched.append(u) or Alive()
        try:
            running = {}
            now = datetime(2026, 10, 22, 15, 0, tzinfo=TOKYO)
            scheduler.tick(now, running)
            scheduler.tick(now, running)  # 前の確認が動いている間は、もう一度始めない
        finally:
            scheduler.launch_check = original
        self.assertEqual(launched, ["friend1"])
        self.assertEqual(account_checks.load_check("friend1")["status"], account_checks.STATUS_RUNNING)


    def test_restart_decision(self):
        d = scheduler.restart_decision
        self.assertEqual(d("a", "a", "a", False, False), scheduler.UPDATE_NONE)
        self.assertEqual(d("a", "a", "b", False, False), scheduler.UPDATE_SETTLING)  # 書き換わった直後はもう1回待つ
        self.assertEqual(d("a", "b", "b", False, True), scheduler.UPDATE_BUSY)
        self.assertEqual(d("a", "b", "b", False, False), scheduler.UPDATE_RESTART)
        self.assertEqual(d("a", "b", "b", True, False), scheduler.UPDATE_NEEDS_INSTALL)
        self.assertEqual(d("a", "a", "a", True, False), scheduler.UPDATE_NEEDS_INSTALL)  # 部品だけが変わったときも

    def test_code_fingerprint_ignores_tests_and_data(self):
        folder = Path(self.tmp.name) / "code"
        folder.mkdir()
        (folder / "a.py").write_text("x = 1", encoding="utf-8")
        before = scheduler.code_fingerprint(folder)
        (folder / "test_a.py").write_text("y = 1", encoding="utf-8")
        (folder / "notes.txt").write_text("z", encoding="utf-8")
        self.assertEqual(scheduler.code_fingerprint(folder), before)
        (folder / "a.py").write_text("x = 2", encoding="utf-8")
        self.assertNotEqual(scheduler.code_fingerprint(folder), before)

    def test_launch_soon(self):
        plans = [plan("q", AUTO_QUEUED)]  # 10/22 15:50 に起動する予定
        self.assertFalse(scheduler.launch_soon(plans, datetime(2026, 10, 22, 15, 34, tzinfo=TOKYO)))
        self.assertTrue(scheduler.launch_soon(plans, datetime(2026, 10, 22, 15, 35, tzinfo=TOKYO)))
        self.assertFalse(scheduler.launch_soon([plan("off", AUTO_OFF)], datetime(2026, 10, 22, 15, 49, tzinfo=TOKYO)))

    def test_heartbeat_note_and_clear(self):
        now = datetime(2026, 10, 22, 15, 0, tzinfo=TOKYO)
        plans_store.write_heartbeat(now, "お知らせ")
        self.assertEqual(plans_store.scheduler_note(), "お知らせ")
        self.assertTrue(scheduler.already_running(now))
        plans_store.clear_heartbeat()
        self.assertFalse(scheduler.already_running(now))
        self.assertEqual(plans_store.scheduler_note(), "")


if __name__ == "__main__":
    unittest.main()
