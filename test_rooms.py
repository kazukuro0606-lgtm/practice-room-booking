import unittest

from booking_rules import PRACTICE_ENSEMBLE, PRACTICE_SOLO
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

    def test_only_verified_rooms_are_usable(self):
        usable = usable_rooms()
        self.assertIn("E224", usable)
        self.assertIn("E320", usable)
        self.assertIn("E452", usable)
        for unchecked in ("E312", "E313", "E412", "E420", "E441"):
            self.assertNotIn(unchecked, usable)

    def test_defaults_and_legacy_favorites(self):
        self.assertEqual(rooms_setting({}), DEFAULT_ROOMS)
        legacy = rooms_setting({"favorite_rooms": ["E330", "E321"]})
        self.assertEqual(legacy[PRACTICE_SOLO][:3], ["E330", "E321", "E320"])
        self.assertEqual(legacy[PRACTICE_ENSEMBLE], ["E452"])
        chosen = rooms_setting({"rooms": {PRACTICE_SOLO: ["E224", "E441", "E330"], PRACTICE_ENSEMBLE: []}})
        self.assertEqual(chosen[PRACTICE_SOLO], ["E224", "E330"])  # 確かめていない部屋は外す
        self.assertEqual(chosen[PRACTICE_ENSEMBLE], ["E452"])  # 空なら初期値

    def test_rooms_for_plan(self):
        to_try, too_long = rooms_for_plan(["E452", "E320", "E321", "E322", "E323", "E324", "E325"], 150)
        self.assertEqual(to_try, ["E320", "E321", "E322", "E323", "E324"])  # 最大5室
        self.assertEqual(too_long, ["E452"])  # E452 は2時間まで
        to_try, _ = rooms_for_plan(["E452"], 120)
        self.assertEqual(to_try, ["E452"])
        self.assertTrue(needs_members(to_try))
        self.assertFalse(needs_members(["E320"]))


if __name__ == "__main__":
    unittest.main()
