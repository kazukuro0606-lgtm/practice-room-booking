import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import app_auth

STRONG = "cello-Tuning-42"
STRONG2 = "brass-Quintet-17"
STRONG3 = "Etude-station-88"


class AppAuthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app_auth.USERS_FILE = Path(self.tmp.name) / "data" / "users.json"
        app_auth.ATTEMPTS_FILE = Path(self.tmp.name) / "data" / "login_attempts.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_users_rejects_everything(self):
        self.assertFalse(app_auth.has_users())
        self.assertFalse(app_auth.verify("kazu", "anything123"))

    def test_users_are_separate(self):
        app_auth.add_user("kazu", STRONG, is_admin=True)
        app_auth.add_user("friend1", STRONG2)
        self.assertTrue(app_auth.verify("kazu", STRONG))
        self.assertFalse(app_auth.verify("kazu", STRONG2))
        self.assertTrue(app_auth.verify("friend1", STRONG2))
        self.assertTrue(app_auth.is_admin("kazu"))
        self.assertFalse(app_auth.is_admin("friend1"))
        self.assertEqual(app_auth.list_users(), ["friend1", "kazu"])

    def test_password_is_not_stored_in_plain_text(self):
        app_auth.add_user("kazu", STRONG)
        text = app_auth.USERS_FILE.read_text(encoding="utf-8")
        self.assertNotIn(STRONG, text)
        self.assertEqual(set(json.loads(text)["kazu"]), {"salt", "hash", "is_admin", "must_change"})

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ValueError):
            app_auth.add_user("kazu", "short")
        with self.assertRaises(ValueError):
            app_auth.add_user("Kazu Kuro", STRONG)
        app_auth.add_user("kazu", STRONG)
        with self.assertRaises(ValueError):
            app_auth.add_user("kazu", STRONG2)

    def test_weak_passwords_are_rejected(self):
        self.assertIsNotNone(app_auth.password_problem("cel7-Tu"))  # 短い（7文字）
        self.assertIsNone(app_auth.password_problem("cel7-Tun"))  # 8文字はよい
        self.assertIsNotNone(app_auth.password_problem("abc12345"))  # 推測されやすい並び
        self.assertIsNotNone(app_auth.password_problem("123456789012"))  # 数字だけ
        self.assertIsNotNone(app_auth.password_problem("aaaaaaaaaaab"))  # 同じ文字の繰り返し
        self.assertIsNotNone(app_auth.password_problem("mypassword2026"))  # よく使われる言葉
        self.assertIsNotNone(app_auth.password_problem("friend1-cello-99", "friend1"))  # ユーザー名を含む
        self.assertIsNone(app_auth.password_problem(STRONG, "kazu"))

    def test_generated_password_is_strong(self):
        passwords = {app_auth.generate_password() for _ in range(20)}
        self.assertEqual(len(passwords), 20)
        for p in passwords:
            self.assertIsNone(app_auth.password_problem(p))

    def test_reset_and_delete(self):
        app_auth.add_user("friend1", STRONG2, must_change=True)
        self.assertTrue(app_auth.must_change_password("friend1"))  # 管理者が決めた最初のパスワード
        app_auth.set_password("friend1", STRONG3)
        self.assertFalse(app_auth.must_change_password("friend1"))  # 本人が変えた
        self.assertFalse(app_auth.verify("friend1", STRONG2))
        self.assertTrue(app_auth.verify("friend1", STRONG3))
        app_auth.delete_user("friend1")
        self.assertFalse(app_auth.verify("friend1", STRONG3))

    def test_user_lock_survives_and_expires(self):
        now = datetime(2026, 10, 22, 12, 0)
        for i in range(4):
            app_auth.record_failure("friend1", now + timedelta(minutes=i))
        self.assertIsNone(app_auth.login_blocked("friend1", now + timedelta(minutes=4)))
        app_auth.record_failure("friend1", now + timedelta(minutes=4))
        # 5回目でロック。ファイルに残るので、ページを開き直しても同じ
        self.assertIsNotNone(app_auth.login_blocked("friend1", now + timedelta(minutes=5)))
        self.assertIsNone(app_auth.login_blocked("kazu", now + timedelta(minutes=5)))  # ほかの人は使える
        # 最後の失敗から15分たつと解除
        self.assertIsNone(app_auth.login_blocked("friend1", now + timedelta(minutes=19, seconds=1)))
        app_auth.clear_failures("friend1")
        self.assertEqual(app_auth._load_attempts(), [])

    def test_global_lock(self):
        now = datetime(2026, 10, 22, 12, 0)
        for i in range(30):
            app_auth.record_failure(f"guess{i}", now + timedelta(seconds=i))
        self.assertIsNotNone(app_auth.login_blocked("kazu", now + timedelta(minutes=1)))
        self.assertIsNone(app_auth.login_blocked("kazu", now + timedelta(minutes=11)))

    def test_rename_keeps_password_and_role(self):
        app_auth.add_user("kazu", STRONG, is_admin=True)
        app_auth.add_user("friend1", STRONG2, must_change=True)
        app_auth.rename_user("friend1", "sato")
        self.assertEqual(app_auth.list_users(), ["kazu", "sato"])
        self.assertTrue(app_auth.verify("sato", STRONG2))
        self.assertFalse(app_auth.verify("friend1", STRONG2))
        self.assertTrue(app_auth.must_change_password("sato"))
        self.assertFalse(app_auth.is_admin("sato"))
        # 使われている名前・使えない文字の名前には変えられない（変えずにそのまま）
        for bad in ("kazu", "Sato", "s", "sa to"):
            with self.assertRaises(ValueError):
                app_auth.rename_user("sato", bad)
        self.assertEqual(app_auth.list_users(), ["kazu", "sato"])


if __name__ == "__main__":
    unittest.main()
