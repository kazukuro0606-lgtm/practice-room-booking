import unittest

from booking_rules import PRACTICE_ENSEMBLE, PRACTICE_SOLO
from notices import NOTICE_VERSION
from rooms import (
    DEFAULT_ROOMS,
    ROOM_IDS,
    event_id_of,
    needs_members,
    room_label,
    rooms_for_plan,
    rooms_setting,
    usable_rooms,
)


class RoomsTest(unittest.TestCase):
    def test_ids_and_labels(self):
        self.assertEqual(event_id_of("e452室"), 291)
        self.assertEqual(event_id_of("E323"), 233)
        self.assertEqual(room_label("E452"), "E452室(TB.)")
        self.assertEqual(room_label("E320"), "E320室")
        with self.assertRaises(ValueError):
            event_id_of("E999")
        self.assertEqual(len(ROOM_IDS), 73)  # 2階21室・3階33室・4階19室

    def test_usable_rooms_depend_on_notice_approval(self):
        plain = usable_rooms(False)
        for room in ("E224", "E320", "E420", "E430"):
            self.assertIn(room, plain)
        for room in ("E215", "E312", "E313", "E412", "E441", "E452"):
            self.assertNotIn(room, plain)  # 注意事項のある部屋と E313 は、承認していないと使えない
        approved = usable_rooms(True)
        for room in ("E215", "E312", "E414", "E415"):
            self.assertIn(room, approved)
        for room in ("E412", "E432", "E441", "E442", "E451", "E452"):
            self.assertNotIn(room, approved)  # 管楽器コースのみ
            self.assertIn(room, usable_rooms(True, wind=True))
            self.assertNotIn(room, usable_rooms(False, wind=True))  # 注意事項の承認も必要
        self.assertNotIn("E313", approved)  # 担当教員名を設定していないと使えない
        self.assertIn("E313", usable_rooms(True, has_teacher=True))
        self.assertNotIn("E313", usable_rooms(False, has_teacher=True))  # 注意事項の承認も必要

    def test_defaults_and_legacy_favorites(self):
        approved = {"approved_notices": [NOTICE_VERSION], "wind_course": True}
        self.assertEqual(rooms_setting(approved), DEFAULT_ROOMS)
        self.assertEqual(rooms_setting({"approved_notices": [NOTICE_VERSION]})[PRACTICE_ENSEMBLE], [])  # 管楽器コースでない
        self.assertEqual(rooms_setting({})[PRACTICE_ENSEMBLE], [])  # 承認していないと E452 は外れる
        legacy = rooms_setting({"favorite_rooms": ["E330", "E321"]})
        self.assertEqual(legacy[PRACTICE_SOLO][:3], ["E330", "E321", "E320"])
        self.assertEqual(legacy[PRACTICE_ENSEMBLE], [])  # 注意事項を承認するまで E452 は使えない
        chosen = rooms_setting({"rooms": {PRACTICE_SOLO: ["E224", "E313", "E330"], PRACTICE_ENSEMBLE: []}, **approved})
        self.assertEqual(chosen[PRACTICE_SOLO], ["E224", "E330"])  # 使えない部屋は外す
        self.assertEqual(chosen[PRACTICE_ENSEMBLE], ["E452"])  # 空なら初期値

    def test_rooms_for_plan(self):
        to_try, too_long = rooms_for_plan(["E452", "E320", "E321", "E322", "E323", "E324", "E325"], 150, True, wind=True)
        self.assertEqual(to_try, ["E320", "E321", "E322", "E323", "E324"])  # 最大5室
        self.assertEqual(too_long, ["E452"])  # E452 は2時間まで
        to_try, _ = rooms_for_plan(["E452"], 120, True, wind=True)
        self.assertEqual(rooms_for_plan(["E452"], 120, True)[0], [])  # 管楽器コースでない
        self.assertEqual(to_try, ["E452"])
        self.assertEqual(rooms_for_plan(["E452", "E320"], 60, False)[0], ["E320"])  # 承認を取り消した後
        self.assertEqual(rooms_for_plan(["E313", "E320"], 60, True)[0], ["E320"])
        self.assertEqual(rooms_for_plan(["E313", "E320"], 60, True, has_teacher=True)[0], ["E313", "E320"])
        self.assertTrue(needs_members(to_try))
        self.assertFalse(needs_members(["E320"]))


if __name__ == "__main__":
    unittest.main()
