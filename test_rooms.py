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
        self.assertEqual(len(ROOM_IDS), 81)  # 2階28室・3階34室・4階19室

    def test_usable_rooms_depend_on_notice_approval(self):
        plain = usable_rooms(False)
        for room in ("E224", "E320", "E420", "E430"):
            self.assertIn(room, plain)
        for room in ("E215", "E312", "E313", "E412", "E441", "E452"):
            self.assertNotIn(room, plain)  # 注意事項のある部屋と E313 は、承認していないと使えない
        approved = usable_rooms(True)
        for room in ("E215", "E312", "E414", "E415"):
            self.assertIn(room, approved)
        wind_view = set(ROOM_IDS)  # 管楽器コースの人に見える部屋（例）
        piano_view = set(ROOM_IDS) - {"E412", "E432", "E441", "E442", "E451", "E452"}  # 管楽器の部屋が見えない人（例）
        for room in ("E412", "E432", "E441", "E442", "E451", "E452"):
            self.assertNotIn(room, approved)  # 見える部屋がまだ分からないと、コースの部屋は使わない
            self.assertIn(room, usable_rooms(True, visible=wind_view))
            self.assertNotIn(room, usable_rooms(True, visible=piano_view))  # 見えない部屋は使わない
            self.assertNotIn(room, usable_rooms(False, visible=wind_view))  # 注意事項の承認も必要
        self.assertNotIn("E320", usable_rooms(False, visible={"E224"}))  # 見えない部屋は、ふつうの部屋でも使わない
        self.assertNotIn("E313", approved)  # 担当教員名を設定していないと使えない
        self.assertIn("E313", usable_rooms(True, has_teacher=True))
        self.assertNotIn("E313", usable_rooms(False, has_teacher=True))  # 注意事項の承認も必要

    def test_defaults_and_legacy_favorites(self):
        approved = {"approved_notices": [NOTICE_VERSION]}
        everything = set(ROOM_IDS)
        self.assertEqual(rooms_setting(approved, everything), DEFAULT_ROOMS)
        self.assertEqual(rooms_setting(approved)[PRACTICE_ENSEMBLE], [])  # 見える部屋が分かるまで E452 は使わない
        self.assertEqual(rooms_setting({})[PRACTICE_ENSEMBLE], [])  # 承認していないと E452 は外れる
        legacy = rooms_setting({"favorite_rooms": ["E330", "E321"]})
        self.assertEqual(legacy[PRACTICE_SOLO][:3], ["E330", "E321", "E320"])
        self.assertEqual(legacy[PRACTICE_ENSEMBLE], [])  # 注意事項を承認するまで E452 は使えない
        chosen = rooms_setting({"rooms": {PRACTICE_SOLO: ["E224", "E313", "E330"], PRACTICE_ENSEMBLE: []}, **approved}, everything)
        self.assertEqual(chosen[PRACTICE_SOLO], ["E224", "E330"])  # 使えない部屋は外す
        self.assertEqual(chosen[PRACTICE_ENSEMBLE], ["E452"])  # 空なら初期値

    def test_rooms_for_plan(self):
        everything = set(ROOM_IDS)
        to_try, too_long = rooms_for_plan(["E452", "E320", "E321", "E322", "E323", "E324", "E325"], 150, True, visible=everything)
        self.assertEqual(to_try, ["E320", "E321", "E322", "E323", "E324"])  # 最大5室
        self.assertEqual(too_long, ["E452"])  # E452 は2時間まで
        to_try, _ = rooms_for_plan(["E452"], 120, True, visible=everything)
        self.assertEqual(rooms_for_plan(["E452"], 120, True)[0], [])  # 見える部屋が分からない
        self.assertEqual(to_try, ["E452"])
        self.assertEqual(rooms_for_plan(["E452", "E320"], 60, False)[0], ["E320"])  # 承認を取り消した後
        self.assertEqual(rooms_for_plan(["E313", "E320"], 60, True)[0], ["E320"])
        self.assertEqual(rooms_for_plan(["E313", "E320"], 60, True, has_teacher=True)[0], ["E313", "E320"])
        self.assertTrue(needs_members(to_try))
        self.assertFalse(needs_members(["E320"]))


    def test_piano_kinds_cover_rooms_without_overlap(self):
        from rooms import PIANO_ROOMS_BY_KIND, PIANO_UNKNOWN_LABEL, piano_of
        groups = list(PIANO_ROOMS_BY_KIND.values())
        for i, a in enumerate(groups):
            self.assertTrue(a <= set(ROOM_IDS))
            for b in groups[i + 1:]:
                self.assertFalse(a & b)
        self.assertEqual(piano_of("E320"), "アップライト")
        self.assertEqual(piano_of("E341"), "グランド")
        self.assertEqual(piano_of("E324"), "ピアノなし")
        self.assertEqual(piano_of("E452"), "ピアノなし")
        self.assertEqual({r for r in ROOM_IDS if piano_of(r) == PIANO_UNKNOWN_LABEL}, set())  # 全部の部屋を調べた


if __name__ == "__main__":
    unittest.main()
