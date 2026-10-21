"""段階2-4：予約可能日時になったら、実際に予約を送信する。

  python auto_reserve.py --date 2026-10-26 --start 16:30 --minutes 90
  python auto_reserve.py --date 2026-10-26 --start 16:30 --minutes 90 --practice アンサンブル

- 予約可能日時（利用終了の7日前）より前に起動すると、その時刻まで待ってから予約する（PCはつけたまま）。
- 候補の部屋を順に試し、確認画面まで進めた部屋で「登録」を1回だけ押す。押した後は別の部屋を試さない。
- --yes を付けない場合は、登録を押す前に PowerShell で確認を求める。
"""

import argparse
import sys
import time as clock
import tomllib
from datetime import date, datetime, time, timedelta
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

import credentials
from auto_login import LOGIN_PATH, login
from booking_rules import (
    DAILY_LIMIT_MIN,
    DURATION_CHOICES_MIN,
    PRACTICE_ENSEMBLE,
    PRACTICE_SOLO,
    ROOM_TB,
    TOKYO,
    booking_opens_at,
    end_datetime,
    start_datetime,
)
from inspect_page import safe_url
from plans_store import (
    STATUS_BOOKED,
    booked_minutes_on,
    find_plan,
    load_plans,
    load_settings,
    mark_booked,
    record_run,
)
from reserve_dryrun import BASE_URL, CONFIRM_PATH, PAGE_TIMEOUT_MS, NotReached, add_url, ask_members, fill_until_confirm
from rooms import ALL_ROOMS, MAX_MINUTES, NEEDS_MEMBERS, candidates

LOCAL_SETTINGS_FILE = Path(__file__).parent / "local_settings.toml"
MAX_ROOMS_TO_TRY = 5
LOGIN_BEFORE_OPEN = timedelta(minutes=3)
# サイトの時計とのずれに備えて、予約可能日時の少し後に送る
SEND_AFTER_OPEN = timedelta(seconds=2)
# 予約が完了したときの画面の見出し（2026-10-21 の本番テストで確認）
COMPLETE_TITLE = "予約登録完了"


def favorite_rooms(user: str | None) -> list[str]:
    """その人が画面で設定した部屋の順番を優先し、なければ local_settings.toml の favorite_rooms を使う。"""
    if user and (rooms := load_settings(user)["favorite_rooms"]):
        return rooms
    if not LOCAL_SETTINGS_FILE.exists():
        return []
    return tomllib.loads(LOCAL_SETTINGS_FILE.read_text(encoding="utf-8")).get("favorite_rooms", [])


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
    parser.add_argument("--plan-id", help="予定登録の画面で登録した予定の番号（画面から起動するときに使う）")
    parser.add_argument("--date", type=date.fromisoformat, help="利用日（例：2026-10-26）")
    parser.add_argument("--start", type=time.fromisoformat, help="開始時刻（例：16:30）")
    parser.add_argument("--minutes", type=int, choices=DURATION_CHOICES_MIN, help="利用時間（分）")
    parser.add_argument("--practice", choices=[PRACTICE_SOLO, PRACTICE_ENSEMBLE], default=PRACTICE_SOLO)
    parser.add_argument("--yes", action="store_true", help="登録を押す前の確認をしない（全自動）")
    parser.add_argument("--user", help="誰のログイン情報で予約するか（--plan-id のときは予定を登録した人）")
    args = parser.parse_args()
    if not args.plan_id and not (args.date and args.start and args.minutes):
        parser.error("--plan-id か、--date・--start・--minutes の3つを指定してください")
    return args


def apply_plan(args: argparse.Namespace) -> list[str]:
    """登録した予定の内容を args に入れ、1日の合計を確かめる。同時利用者を返す。"""
    plans = load_plans()
    plan = find_plan(plans, args.plan_id)
    if plan["status"] == STATUS_BOOKED:
        raise SystemExit("この予定はすでに予約完了になっています。")
    args.date = date.fromisoformat(plan["use_date"])
    args.start = time.fromisoformat(plan["start"])
    args.minutes = plan["duration_min"]
    # 試す部屋は、予定で選んだ部屋（3階／TB）で決める
    args.practice = PRACTICE_ENSEMBLE if plan["room"] == ROOM_TB else PRACTICE_SOLO
    # 予約は、予定を登録した本人のログイン情報で行う
    args.user = plan.get("owner")
    booked = booked_minutes_on(plans, args.date, exclude_id=plan["id"], owner=args.user)
    total = plan.get("existing_min", 0) + booked + args.minutes
    if total > DAILY_LIMIT_MIN:
        raise SystemExit(f"この日の合計が{total}分になり、{DAILY_LIMIT_MIN}分を超えるため予約しません。")
    return plan.get("members", [])


def main() -> None:
    args = parse_args()
    if not args.plan_id:
        run(args)
        return
    try:
        run(args)
    except SystemExit as e:
        # 途中で止まった理由も予定に記録して、画面で見られるようにする
        if isinstance(e.code, str):
            record_run(args.plan_id, datetime.now(TOKYO), f"中止：{e.code}", [])
        raise


def run(args: argparse.Namespace) -> None:
    plan_members = apply_plan(args) if args.plan_id else None
    # よく使う部屋の順番は、個人練習（3階の部屋）のときだけ使う
    preferred = favorite_rooms(args.user) if args.practice == PRACTICE_SOLO else []
    rooms = candidates(args.practice, preferred, MAX_ROOMS_TO_TRY)
    for room in rooms:
        limit = MAX_MINUTES.get(ALL_ROOMS[room])
        if limit and args.minutes > limit:
            raise SystemExit(f"{room}の利用時間は{limit}分までです。")
    members = None
    if any(ALL_ROOMS[r] in NEEDS_MEMBERS for r in rooms):
        members = plan_members or ask_members()

    start_at = start_datetime(args.date, args.start)
    opens_at = booking_opens_at(end_datetime(start_at, args.minutes))
    send_at = opens_at + SEND_AFTER_OPEN
    who = f"{args.user} の" if args.user else ""
    print(f"{who}予約：{start_at:%Y-%m-%d %H:%M} から {args.minutes}分（{args.practice}）")
    print(f"試す部屋（この順に最大{MAX_ROOMS_TO_TRY}室）：{', '.join(rooms)}")
    print(f"予約可能日時：{opens_at:%Y-%m-%d %H:%M}")
    if datetime.now(TOKYO) < send_at - LOGIN_BEFORE_OPEN:
        wait_until(send_at - LOGIN_BEFORE_OPEN, "ログイン開始")

    login_id, password = credentials.load(args.user)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=False)
        page = browser.new_page()
        page.goto(BASE_URL + "/login/")
        if LOGIN_PATH in page.url:
            login(page, login_id, password)
        wait_until(send_at, "予約開始")

        started_at = datetime.now(TOKYO)
        booked_room = None
        completed = False
        declined = False
        full_rooms = []
        for room in rooms:
            print(f"{room} を試しています…")
            room_members = members if ALL_ROOMS[room] in NEEDS_MEMBERS else None
            try:
                fill_until_confirm(page, add_url(ALL_ROOMS[room], args.date, args.start), args.minutes, members=room_members)
            except NotReached:
                print(f"  {room} は確認画面まで進めませんでした（埋まっている可能性があります）。")
                full_rooms.append(room)
                continue
            if not args.yes:
                answer = input(f"  {room} の確認画面です。Edgeで内容を確認し、予約するなら y と入力して Enter：")
                if answer.strip().lower() != "y":
                    print("予約を送信せずに終了します。")
                    declined = True
                    break
            completed = register(page)
            booked_room = room
            break

        if booked_room and completed:
            result = f"予約完了（{booked_room}）"
            print(f"予約が完了しました：{booked_room}　{start_at:%Y-%m-%d %H:%M} から {args.minutes}分")
        elif booked_room:
            result = f"{booked_room} で登録を押したが、完了画面にならなかった（要確認）"
            print(f"{booked_room} の「登録」を押しましたが、完了画面になりませんでした。")
            print(f"結果の画面：{page.title()}  {safe_url(page.url)}")
            print("Edgeの画面と「予約内容」で、予約が入っているか確認してください。")
        elif declined:
            result = "確認画面で送信をやめた"
            print("予約は送信していません。")
        else:
            result = f"空きなし（{len(full_rooms)}室とも確認画面まで進めなかった）"
            print(f"試した{len(full_rooms)}室とも予約できませんでした。予約は送信していません。")
        if args.plan_id:
            record_run(args.plan_id, started_at, result, full_rooms)
            if completed:
                mark_booked(args.plan_id, booked_room, by="自動")
                print("予定登録の画面で「予約完了」に切り替えました。")
        print("確認できたら、Edgeのウィンドウを閉じてください（閉じると終了します）。")
        page.wait_for_event("close", timeout=0)
        browser.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        if "--plan-id" in sys.argv:
            # 画面から別ウィンドウで起動したときは、結果を読めるように閉じる前に待つ
            input("\nEnter を押すと、このウィンドウを閉じます。")
