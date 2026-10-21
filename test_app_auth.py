import json
import tempfile
import unittest
from pathlib import Path

import app_auth


class AppAuthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app_auth.USERS_FILE = Path(self.tmp.name) / "data" / "users.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_users_rejects_everything(self):
        self.assertFalse(app_auth.has_users())
        self.assertFalse(app_auth.verify("kazu", "anything123"))

    def test_users_are_separate(self):
        app_auth.add_user("kazu", "correct-horse", is_admin=True)
        app_auth.add_user("friend1", "battery-staple")
        self.assertTrue(app_auth.verify("kazu", "correct-horse"))
        self.assertFalse(app_auth.verify("kazu", "battery-staple"))
        self.assertTrue(app_auth.verify("friend1", "battery-staple"))
        self.assertTrue(app_auth.is_admin("kazu"))
        self.assertFalse(app_auth.is_admin("friend1"))
        self.assertEqual(app_auth.list_users(), ["friend1", "kazu"])

    def test_password_is_not_stored_in_plain_text(self):
        app_auth.add_user("kazu", "correct-horse")
        text = app_auth.USERS_FILE.read_text(encoding="utf-8")
        self.assertNotIn("correct-horse", text)
        self.assertEqual(set(json.loads(text)["kazu"]), {"salt", "hash", "is_admin"})

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ValueError):
            app_auth.add_user("kazu", "short")
        with self.assertRaises(ValueError):
            app_auth.add_user("Kazu Kuro", "correct-horse")
        app_auth.add_user("kazu", "correct-horse")
        with self.assertRaises(ValueError):
            app_auth.add_user("kazu", "another-pass")

    def test_reset_and_delete(self):
        app_auth.add_user("friend1", "battery-staple")
        app_auth.set_password("friend1", "new-password")
        self.assertFalse(app_auth.verify("friend1", "battery-staple"))
        self.assertTrue(app_auth.verify("friend1", "new-password"))
        app_auth.delete_user("friend1")
        self.assertFalse(app_auth.verify("friend1", "new-password"))


if __name__ == "__main__":
    unittest.main()
