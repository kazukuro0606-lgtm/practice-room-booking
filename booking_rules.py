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

PRACTICE_SOLO = "個人練習"
PRACTICE_ENSEMBLE = "アンサンブル"
ROOM_3F = "3階の部屋（どこでも）"
ROOM_TB = "TBの部屋"

# 練習の種類ごとに使う部屋
ROOM_FOR_PRACTICE = {PRACTICE_SOLO: ROOM_3F, PRACTICE_ENSEMBLE: ROOM_TB}


@dataclass(frozen=True)
class Check:
    end_at: datetime
    opens_at: datetime
    daily_total_min: int
    over_daily_limit: bool
    room_advice: str | None


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


def room_advice(practice_type: str, room: str) -> str | None:
    """個人練習は3階の部屋、アンサンブルはTBの部屋を使う。"""
    expected = ROOM_FOR_PRACTICE.get(practice_type)
    if expected and room != expected:
        return f"{practice_type}では「{expected}」を使います。"
    return None


def check_plan(
    use_date: date,
    start_time: time,
    duration_min: int,
    existing_min: int,
    practice_type: str,
    room: str,
) -> Check:
    start_at = start_datetime(use_date, start_time)
    end_at = end_datetime(start_at, duration_min)
    total = daily_total(existing_min, duration_min)
    return Check(
        end_at=end_at,
        opens_at=booking_opens_at(end_at),
        daily_total_min=total,
        over_daily_limit=total > DAILY_LIMIT_MIN,
        room_advice=room_advice(practice_type, room),
    )
