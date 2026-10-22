import unittest
from datetime import date, datetime, time

from booking_rules import TOKYO, check_plan, end_datetime, has_short_gap, start_datetime, within_hours


class BookingRulesTest(unittest.TestCase):
    def test_opens_7_days_before_end(self):
        # 2026-10-28 15〜16時 → 2026-10-21 16時から予約可能
        c = check_plan(date(2026, 10, 28), time(15, 0), 60, 0)
        self.assertEqual(c.end_at, datetime(2026, 10, 28, 16, 0, tzinfo=TOKYO))
        self.assertEqual(c.opens_at, datetime(2026, 10, 21, 16, 0, tzinfo=TOKYO))

    def test_daily_limit_180_is_ok_181_warns(self):
        ok = check_plan(date(2026, 10, 28), time(15, 0), 90, 90)
        self.assertEqual(ok.daily_total_min, 180)
        self.assertFalse(ok.over_daily_limit)
        over = check_plan(date(2026, 10, 28), time(15, 0), 30, 151)
        self.assertTrue(over.over_daily_limit)

    def test_durations_up_to_3_hours(self):
        start = start_datetime(date(2026, 10, 28), time(15, 0))
        self.assertEqual(end_datetime(start, 180), datetime(2026, 10, 28, 18, 0, tzinfo=TOKYO))
        with self.assertRaises(ValueError):
            end_datetime(start, 210)

    def test_rejects_unknown_duration_and_negative_existing(self):
        start = start_datetime(date(2026, 10, 28), time(15, 0))
        with self.assertRaises(ValueError):
            end_datetime(start, 45)
        with self.assertRaises(ValueError):
            check_plan(date(2026, 10, 28), time(15, 0), 60, -30)

    def test_within_university_hours(self):
        self.assertTrue(within_hours(time(7, 0), 60))
        self.assertTrue(within_hours(time(19, 0), 180))  # 22:00 ちょうどに終わる
        self.assertFalse(within_hours(time(6, 30), 60))
        self.assertFalse(within_hours(time(21, 30), 60))  # 22:30 まではみ出す

    def test_short_gap(self):
        others = [(time(9, 0), time(9, 30))]
        self.assertTrue(has_short_gap(others, time(10, 0), time(10, 30)))  # 9:30〜10:00 の30分の空き
        self.assertTrue(has_short_gap(others, time(8, 0), time(8, 30)))  # 後ろ側にも30分の空き
        self.assertFalse(has_short_gap(others, time(9, 30), time(10, 0)))  # ちょうど続いている
        self.assertFalse(has_short_gap(others, time(10, 30), time(11, 0)))  # 1時間あいている


if __name__ == "__main__":
    unittest.main()
