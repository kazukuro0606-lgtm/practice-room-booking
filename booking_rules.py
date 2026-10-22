"""練習室予約の判定ルール（画面にもファイル保存にも依存しない純粋な関数）。"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TOKYO = ZoneInfo("Asia/Tokyo")

# 利用時間の選択肢（予約サイトの選択肢のうち3時間まで）
DURATION_CHOICES_MIN = (30, 60, 90, 120, 150, 180)

# 同じ利用日の既存予約＋希望予約の合計がこれを超えたら警告する
DAILY_LIMIT_MIN = 180

# 予約受付は利用終了日時のこの日数前から
OPEN_DAYS_BEFORE_END = 7

# 大学の予約ルール（エチュードステーション練習室予約について）
OPEN_TIME = time(7, 0)  # 7時から
CLOSE_TIME = time(22, 0)  # 22時まで
MAX_BOOKINGS_PER_DAY = 4  # 1日の利用時間は最大4回に分けて予約できる
# 30分おきに予約と空きを交互に作る使い方は、規程を超える利用とみなされることがある
SHORT_GAP = timedelta(minutes=30)

PRACTICE_SOLO = "個人練習"
PRACTICE_ENSEMBLE = "アンサンブル"

# 部屋を人ごとに選べるようになる前の予定の「希望する部屋」（部屋ごとの決まりは rooms.py）
LEGACY_ROOM_3F = "3階の部屋（どこでも）"
LEGACY_ROOM_TB = "TBの部屋"


@dataclass(frozen=True)
class Check:
    end_at: datetime
    opens_at: datetime
    daily_total_min: int
    over_daily_limit: bool


def start_datetime(use_date: date, start_time: time) -> datetime:
    return datetime.combine(use_date, start_time, tzinfo=TOKYO)


def end_datetime(start_at: datetime, duration_min: int) -> datetime:
    if duration_min not in DURATION_CHOICES_MIN:
        raise ValueError(f"利用時間は {DURATION_CHOICES_MIN} 分から選んでください")
    return start_at + timedelta(minutes=duration_min)


def booking_opens_at(end_at: datetime) -> datetime:
    """予約可能日時＝利用終了日時の7日前。"""
    return end_at - timedelta(days=OPEN_DAYS_BEFORE_END)


def daily_total(existing_min: int, duration_min: int) -> int:
    if existing_min < 0:
        raise ValueError("既存予約時間は0分以上で入力してください")
    return existing_min + duration_min


def check_plan(
    use_date: date,
    start_time: time,
    duration_min: int,
    existing_min: int,
) -> Check:
    start_at = start_datetime(use_date, start_time)
    end_at = end_datetime(start_at, duration_min)
    total = daily_total(existing_min, duration_min)
    return Check(
        end_at=end_at,
        opens_at=booking_opens_at(end_at),
        daily_total_min=total,
        over_daily_limit=total > DAILY_LIMIT_MIN,
    )


def within_hours(start_time: time, duration_min: int) -> bool:
    """7時〜22時の中に収まるか。"""
    start = datetime.combine(date(2000, 1, 1), start_time)
    end = start + timedelta(minutes=duration_min)
    return start_time >= OPEN_TIME and end <= datetime.combine(date(2000, 1, 1), CLOSE_TIME)


def has_short_gap(others: list[tuple[time, time]], start_time: time, end_time: time) -> bool:
    """同じ日のほかの予定との間に、30分以下の空きができるか（ちょうど続いている・重なっているときは数えない）。"""
    day = date(2000, 1, 1)
    start = datetime.combine(day, start_time)
    end = datetime.combine(day, end_time)
    for other_start, other_end in others:
        before = start - datetime.combine(day, other_end)  # ほかの予定の後に、この予定が来るとき
        after = datetime.combine(day, other_start) - end  # この予定の後に、ほかの予定が来るとき
        if timedelta(0) < before <= SHORT_GAP or timedelta(0) < after <= SHORT_GAP:
            return True
    return False
