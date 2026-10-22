import unittest

from rooms import compare_room_options


class ListRoomsTest(unittest.TestCase):
    def test_new_changed_and_missing_rooms(self):
        options = ["=すべて表示", "999=E399室", "120=E320室", "777=E321室"]
        lines = compare_room_options(options)
        text = "\n".join(lines)
        self.assertIn("E399：番号 999", text)  # アプリに未登録
        self.assertIn("E321：アプリでは 121、画面では 777", text)  # 番号が違う
        self.assertNotIn("E320：", text)  # 一致している部屋は書かない
        missing = lines[lines.index("[アプリにあるが、この画面に出ていない部屋]") + 1]
        self.assertIn("E452", missing)
        self.assertNotIn("E320", missing)


if __name__ == "__main__":
    unittest.main()
