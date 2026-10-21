import json
import tempfile
import unittest
from pathlib import Path

import app_auth


class AppAuthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        app_auth.AUTH_FILE = Path(self.tmp.name) / "data" / "auth.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_configured_rejects_everything(self):
        self.assertFalse(app_auth.is_configured())
        self.assertFalse(app_auth.verify("anything123"))

    def test_set_and_verify(self):
        app_auth.set_password("correct-horse")
        self.assertTrue(app_auth.verify("correct-horse"))
        self.assertFalse(app_auth.verify("wrong-horse"))

    def test_password_is_not_stored_in_plain_text(self):
        app_auth.set_password("correct-horse")
        self.assertNotIn("correct-horse", app_auth.AUTH_FILE.read_text(encoding="utf-8"))
        self.assertEqual(set(json.loads(app_auth.AUTH_FILE.read_text(encoding="utf-8"))), {"salt", "hash"})

    def test_short_password_is_rejected(self):
        with self.assertRaises(ValueError):
            app_auth.set_password("short")
        self.assertFalse(app_auth.is_configured())


if __name__ == "__main__":
    unittest.main()
