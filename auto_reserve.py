"""段階2-4：予約可能日時になったら、実際に予約を送信する。

  python auto_reserve.py --date 2026-10-26 --start 16:30 --minutes 90
  python auto_reserve.py --date 2026-10-26 --start 16:30 --minutes 90 --practice アンサンブル

- 予約可能日時（利用終了の7日前）より前に起動すると、その時刻まで待ってから予約する（PCはつけたまま）。
- 候補の部屋を順に試し、確認画面まで進めた部屋で「登録」を1回だけ押す。押した後は別の部屋を試さない。
- --yes を付けない場合は、登録を押す前に PowerShell で確認を求める。
"""

import argparse
import time as clock
import tomllib
from datetime import date, datetime, time, timedelta
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

import credentials
from auto_login import LOGIN_PATH, login
from booking_rules import (
    DURATION_CHOICES_MIN,
    PRACTICE_ENSEMBLE,
    PRACTICE_SOLO,
    TOKYO,
    booking_opens_at,
    end_datetime,
    start_datetime,
)
from inspect_page import safe_url
from reserve_dryrun import BASE_URL, CONFIRM_PATH, PAGE_TIMEOUT_MS, NotReached, add_url, ask_members, fill_until_confirm
from rooms import ALL_ROOMS, MAX_MINUTES, NEEDS_MEMBERS, candidates

SETTINGS_FILE = Path(__file__).parent / "local_settings.toml"
MAX_ROOMS_TO_TRY = 5
LOGIN_BEFORE_OPEN = timedelta(minutes=3)
# サイトの時計とのずれに備えて、予約可能日時の少し後に送る
SEND_AFTER_OPEN = timedelta(seconds=2)
# 予約が完了したときの画面の見出し（2026-10-21 の本番テストで確認）
COMPLETE_TITLE = "予約登録完了"


def favorite_rooms() -> list[str]:
    if not SETTINGS_FILE.exists():
        return []
    return tomllib.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("favorite_rooms", [])


def wait_until(target: datetime, label: str) -> None:
    while (remaining := (target - datetime.now(TOKYO)).total_seconds()) > 0:
        print(f"\r{label}（{target:%m/%d %H:%M:%S}）まであと {int(remaining)} 秒   ", end="", flush=True)
        clock.sleep(min(remaining, 1))
    print()


def register(page: Page) -> bool:
    """確認画面の「登録」を1回だけ押し、完了画面になったかを返す。"""
    page.click("#register")
    try:
        page.wait_for_url(lambda u: CONFIRM_PATH not in u, timeout=PAGE_TIMEOUT_MS)
    except Exception:
        pass  # 画面が変わらなくても、押し直しはしない
    return COMPLETE_TITLE in page.title()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="予約可能日時になったら予約を送信する")
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="利用日（例：2026-10-26）")
    parser.add_argument("--start", type=time.fromisoformat, required=True, help="開始時刻（例：16:30）")
    parser.add_argument("--minutes", type=int, choices=DURATION_CHOICES_MIN, required=True, help="利用時間（分）")
    parser.add_argument("--practice", choices=[PRACTICE_SOLO, PRACTICE_ENSEMBLE], default=PRACTICE_SOLO)
    parser.add_argument("--yes", action="store_true", help="登録を押す前の確認をしない（全自動）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rooms = candidates(args.practice, favorite_rooms(), MAX_ROOMS_TO_TRY)
    for room in rooms:
        limit = MAX_MINUTES.get(ALL_ROOMS[room])
        if limit and args.minutes > limit:
            raise SystemExit(f"{room}の利用時間は{limit}分までです。")
    members = ask_members() if any(ALL_ROOMS[r] in NEEDS_MEMBERS for r in rooms) else None

    start_at = start_datetime(args.date, args.start)
    opens_at = booking_opens_at(end_datetime(start_at, args.minutes))
    send_at = opens_at + SEND_AFTER_OPEN
    print(f"予約：{start_at:%Y-%m-%d %H:%M} から {args.minutes}分（{args.practice}）")
    print(f"試す部屋（この順に最大{MAX_ROOMS_TO_TRY}室）：{', '.join(rooms)}")
    print(f"予約可能日時：{opens_at:%Y-%m-%d %H:%M}")
    if datetime.now(TOKYO) < send_at - LOGIN_BEFORE_OPEN:
        wait_until(send_at - LOGIN_BEFORE_OPEN, "ログイン開始")

    login_id, password = credentials.load()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=False)
        page = browser.new_page()
        page.goto(BASE_URL + "/login/")
        if LOGIN_PATH in page.url:
            login(page, login_id, password)
        wait_until(send_at, "予約開始")

        booked_room = None
        completed = False
        for room in rooms:
            print(f"{room} を試しています…")
            room_members = members if ALL_ROOMS[room] in NEEDS_MEMBERS else None
            try:
                fill_until_confirm(page, add_url(ALL_ROOMS[room], args.date, args.start), args.minutes, members=room_members)
            except NotReached:
                print(f"  {room} は確認画面まで進めませんでした（埋まっている可能性があります）。")
                continue
            if not args.yes:
                answer = input(f"  {room} の確認画面です。Edgeで内容を確認し、予約するなら y と入力して Enter：")
                if answer.strip().lower() != "y":
                    print("予約を送信せずに終了します。")
                    break
            completed = register(page)
            booked_room = room
            break

        if booked_room and completed:
            print(f"予約が完了しました：{booked_room}　{start_at:%Y-%m-%d %H:%M} から {args.minutes}分")
        elif booked_room:
            print(f"{booked_room} の「登録」を押しましたが、完了画面になりませんでした。")
            print(f"結果の画面：{page.title()}  {safe_url(page.url)}")
            print("Edgeの画面と「予約内容」で、予約が入っているか確認してください。")
        else:
            print("予約は送信していません。")
        print("確認できたら、Edgeのウィンドウを閉じてください（閉じると終了します）。")
        page.wait_for_event("close", timeout=0)
        browser.close()


if __name__ == "__main__":
    main()
