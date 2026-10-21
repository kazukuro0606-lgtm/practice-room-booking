import unittest
from datetime import date, datetime, time

from booking_rules import TOKYO, check_plan, end_datetime, start_datetime


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


if __name__ == "__main__":
    unittest.main()
