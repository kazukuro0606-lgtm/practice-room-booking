import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import email_verify
import mailer
import notify
import plans_store
from booking_rules import TOKYO
from plans_store import STATUS_BOOKED, STATUS_PLANNED, save_plans, save_settings

NOW = datetime(2026, 10, 22, 13, 0, tzinfo=TOKYO)


def plan(status, **extra):
    return {"id": "p1", "owner": "sato", "use_date": "2026-10-29", "start": "12:30", "end": "14:00",
            "duration_min": 90, "status": status, **extra}


class EmailVerifyTest(unittest.TestCase):
    def test_right_code_within_time(self):
        pending = email_verify.pending_for("a@example.com", "012345", NOW)
        self.assertNotIn("012345", str(pending))  # 番号そのものは保存しない
        self.assertEqual(email_verify.check(pending, " 012345 ", NOW + timedelta(minutes=29)), (True, None))

    def test_wrong_expired_and_too_many_tries(self):
        pending = email_verify.pending_for("a@example.com", "012345", NOW)
        self.assertFalse(email_verify.check(pending, "012346", NOW)[0])
        self.assertFalse(email_verify.check(pending, "abc", NOW)[0])
        self.assertFalse(email_verify.check(pending, "012345", NOW + timedelta(minutes=31))[0])
        self.assertFalse(email_verify.check({**pending, "tries": email_verify.MAX_TRIES}, "012345", NOW)[0])
        self.assertFalse(email_verify.check(None, "012345", NOW)[0])

    def test_codes_are_six_digits(self):
        for _ in range(50):
            code = email_verify.new_code()
            self.assertEqual(len(code), 6)
            self.assertTrue(code.isdigit())


class MailerTest(unittest.TestCase):
    def test_address_check_rejects_header_tricks(self):
        self.assertIsNone(mailer.address_problem("friend.1+room@example.co.jp"))
        for bad in ("", "no-at.example.com", "a@b", "a@example.com\nBcc: x@example.com", "a b@example.com"):
            self.assertIsNotNone(mailer.address_problem(bad), bad)
        with self.assertRaises(ValueError):
            mailer.build_message("me@gmail.com", "a@example.com\nBcc: x@example.com", "件名", "本文")

    def test_send_uses_gmail_with_normalized_app_password(self):
        smtp = mock.MagicMock()
        with mock.patch("mailer.smtplib.SMTP_SSL", return_value=smtp) as cls:
            mailer.send("a@example.com", "件名", "本文", sender_address="me@gmail.com", app_password="abcd efgh ijkl mnop")
        self.assertEqual(cls.call_args.args[:2], ("smtp.gmail.com", 465))
        session = smtp.__enter__.return_value
        session.login.assert_called_once_with("me@gmail.com", "abcdefghijklmnop")
        message = session.send_message.call_args.args[0]
        self.assertEqual(message["To"], "a@example.com")
        self.assertEqual(message["Subject"], "件名")


class NotifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        plans_store.DATA_FILE = Path(self.tmp.name) / "data" / "plans.json"
        plans_store.SETTINGS_DIR = Path(self.tmp.name) / "data" / "settings"

    def tearDown(self):
        self.tmp.cleanup()

    def test_messages(self):
        subject, body = notify.result_message(plan(STATUS_BOOKED, booked_room="E320", last_run={"result": "予約完了（E320）"}))
        self.assertEqual(subject, "【練習室】予約完了 10/29（木）12:30〜14:00 E320")
        self.assertIn("部屋：E320", body)
        subject, body = notify.result_message(plan(STATUS_PLANNED, last_run={"result": "空きなし（3室とも確認画面まで進めなかった）"}))
        self.assertTrue(subject.startswith("【練習室】予約できませんでした"))
        self.assertIn("結果：空きなし", body)

    def test_sends_only_to_registered_owner(self):
        save_plans([plan(STATUS_BOOKED, booked_room="E320", last_run={"result": "予約完了（E320）"})])
        with mock.patch("notify.mailer.configured", return_value=True), mock.patch("notify.mailer.send") as send:
            notify.notify_plan_result("p1")  # まだ登録していない
            send.assert_not_called()
            save_settings("sato", {**plans_store.DEFAULT_SETTINGS, "email": "sato@example.com"})
            notify.notify_plan_result("p1")
            self.assertEqual(send.call_args.args[0], "sato@example.com")
            notify.notify_plan_result("deleted")  # 予定が消されていても止まらない

    def test_mail_failure_does_not_raise(self):
        save_plans([plan(STATUS_PLANNED, last_run={"result": "空きなし"})])
        save_settings("sato", {**plans_store.DEFAULT_SETTINGS, "email": "sato@example.com"})
        with mock.patch("notify.mailer.configured", return_value=True), \
                mock.patch("notify.mailer.send", side_effect=OSError("network")):
            notify.notify_plan_result("p1")


if __name__ == "__main__":
    unittest.main()
