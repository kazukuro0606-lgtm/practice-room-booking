"""段階2-4：予約可能日時になったら、実際に予約を送信する。

  python auto_reserve.py --date 2026-10-26 --start 16:30 --minutes 90
  python auto_reserve.py --date 2026-10-26 --start 16:30 --minutes 90 --practice アンサンブル

- 予約可能日時（利用終了の7日前）より前に起動すると、その時刻まで待ってから予約する（PCはつけたまま）。
- 候補の部屋（予定に保存した部屋、またはその人の設定の部屋）を順に最大5室試し、確認画面まで進めた部屋で
  「登録」を1回だけ押す。押した後は別の部屋を試さない。
- --yes を付けない場合は、登録を押す前に PowerShell で確認を求める。
"""

import argparse
import sys
import time as clock
from datetime import date, datetime, time, timedelta

from playwright.sync_api import Page, sync_playwright

import credentials
from auto_login import LOGIN_PATH, login
from booking_rules import (
    CLOSE_TIME,
    DAILY_LIMIT_MIN,
    MAX_BOOKINGS_PER_DAY,
    OPEN_TIME,
    DURATION_CHOICES_MIN,
    PRACTICE_ENSEMBLE,
    LEGACY_ROOM_TB,
    PRACTICE_SOLO,
    TOKYO,
    booking_opens_at,
    end_datetime,
    start_datetime,
    within_hours,
)
from check_room import mask_numbers
from inspect_page import safe_url
from plans_store import (
    AUTO_RUNNING,
    STATUS_BOOKED,
    auto_state,
    booked_count_on,
    booked_minutes_on,
    find_plan,
    load_plans,
    load_settings,
    mark_booked,
    record_run,
)
from reserve_dryrun import BASE_URL, CONFIRM_PATH, PAGE_TIMEOUT_MS, NotReached, add_url, ask_members, fill_until_confirm
from rooms import (
    MAX_ROOMS_TO_TRY,
    NEEDS_MEMBERS,
    NOTICE_ROOMS,
    TEACHER_ROOMS,
    WIND_ONLY_ROOMS,
    event_id_of,
    needs_members,
    notice_approved,
    rooms_for_plan,
    rooms_setting,
)

LOGIN_BEFORE_OPEN = timedelta(minutes=3)
# サイトの時計とのずれに備えて、予約可能日時の少し後に送る
SEND_AFTER_OPEN = timedelta(seconds=2)
# 予約が完了したときの画面の見出し（2026-10-21 の本番テストで確認）
COMPLETE_TITLE = "予約登録完了"


def chosen_rooms(user: str | None, practice: str) -> list[str]:
    """その人が設定した、練習の種類ごとの部屋（設定がなければ初期値）。"""
    return rooms_setting(load_settings(user) if user else {})[practice]


def approved_by(user: str | None) -> bool:
    """予約する本人が、注意事項の今の文面を承認しているか（ユーザーなしで直接動かすときは、動かした本人が承認したとみなす）。"""
    return notice_approved(load_settings(user)) if user else True


def wind_of(user: str | None) -> bool:
    """予約する本人が管楽器コースか（ユーザーなしで直接動かすときは、動かした本人が決めたとみなす）。"""
    return bool(load_settings(user).get("wind_course")) if user else True


def teacher_of(user: str | None) -> str | None:
    """予約する本人が設定した担当教員名（E313 で使う）。"""
    return (load_settings(user).get("teacher_name") or None) if user else None


def wait_until(target: datetime, label: str) -> None:
    while (remaining := (target - datetime.now(TOKYO)).total_seconds()) > 0:
        print(f"\r{label}（{target:%m/%d %H:%M:%S}）まであと {int(remaining)} 秒   ", end="", flush=True)
        clock.sleep(min(remaining, 1))
    print()


# 確認画面に表示されるメッセージのうち、予約できない理由らしい行を拾う言葉
REASON_WORDS = ("できません", "できない", "エラー", "超え", "上限", "不可", "重複", "既に", "すでに", "期間", "受付", "ありません")
# この言葉が理由に含まれるときは、本人の申し込み数が予約サイトの上限に達している。どの部屋でも同じなので、ほかの部屋は試さない
LIMIT_WORDS = ("申し込み数", "申込数", "申し込み件数", "申込件数")
# 確認画面に「登録」ボタンが出るのを待つ時間
REGISTER_WAIT_MS = 5_000


def page_reason(page: Page) -> str:
    """確認画面などに出ている、予約できない理由らしい文を短く取り出す（学籍番号などの数字の並びは伏せる）。"""
    try:
        lines = [line.strip() for line in page.inner_text("body").splitlines() if line.strip()]
    except Exception:
        return "画面の文字を読めませんでした"
    picked = [line for line in lines if any(word in line for word in REASON_WORDS)][:3]
    text = " / ".join(picked) if picked else f"画面の見出し：{page.title()}"
    return mask_numbers(text)[:200]


def has_register_button(page: Page) -> bool:
    try:
        page.locator("#register").wait_for(state="visible", timeout=REGISTER_WAIT_MS)
        return True
    except Exception:
        return False


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
    parser.add_argument(
        "--unattended", action="store_true", help="予約係（scheduler.py）から起動する。全自動・Edgeを画面に出さない・終わったら閉じる"
    )
    args = parser.parse_args()
    if args.unattended:
        args.yes = True
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
    # 予約は、予定を登録した本人のログイン情報で行う
    args.user = plan.get("owner")
    if plan.get("rooms"):
        # 登録したときに決めた部屋を、その順に試す
        args.practice = plan["practice_type"]
        args.rooms = plan["rooms"]
    else:
        # 部屋を人ごとに選べるようになる前の予定（希望する部屋：3階／TB）
        args.practice = PRACTICE_ENSEMBLE if plan.get("room") == LEGACY_ROOM_TB else PRACTICE_SOLO
        args.rooms = None
    booked = booked_minutes_on(plans, args.date, exclude_id=plan["id"], owner=args.user)
    total = plan.get("existing_min", 0) + booked + args.minutes
    if total > DAILY_LIMIT_MIN:
        raise SystemExit(f"この日の合計が{total}分になり、{DAILY_LIMIT_MIN}分を超えるため予約しません。")
    count = booked_count_on(plans, args.date, exclude_id=plan["id"], owner=args.user) + 1
    if count > MAX_BOOKINGS_PER_DAY:
        raise SystemExit(f"この日の予約が{count}回目になり、1日{MAX_BOOKINGS_PER_DAY}回までを超えるため予約しません。")
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
    except Exception as e:
        # 例外の文面に入力値が含まれる可能性があるので、記録するのは種類だけ
        record_run(args.plan_id, datetime.now(TOKYO), f"エラーで中止（{type(e).__name__}）", [])
        raise


def run(args: argparse.Namespace) -> None:
    plan_members = apply_plan(args) if args.plan_id else None
    if not within_hours(args.start, args.minutes):
        raise SystemExit(f"利用時間が{OPEN_TIME:%H:%M}〜{CLOSE_TIME:%H:%M}に収まらないため予約しません。")
    chosen = getattr(args, "rooms", None) or chosen_rooms(args.user, args.practice)
    approved = approved_by(args.user)
    if not approved and (unapproved := [r for r in chosen if r in NOTICE_ROOMS]):
        print(f"注意事項を承認していないため試さない部屋：{', '.join(unapproved)}")
    teacher = teacher_of(args.user)
    if not teacher and (no_teacher := [r for r in chosen if r in TEACHER_ROOMS]):
        print(f"担当教員名を設定していないため試さない部屋：{', '.join(no_teacher)}")
    wind = wind_of(args.user)
    if not wind and (wind_only := [r for r in chosen if r in WIND_ONLY_ROOMS]):
        print(f"管楽器コースと設定していないため試さない部屋：{', '.join(wind_only)}")
    rooms, too_long = rooms_for_plan(chosen, args.minutes, approved, has_teacher=bool(teacher), wind=wind)
    if too_long:
        print(f"利用時間が長すぎるため試さない部屋：{', '.join(too_long)}")
    if not rooms:
        raise SystemExit("この利用時間で予約できる部屋がありません（部屋の設定か利用時間を見直してください）。")
    members = None
    if needs_members(rooms):
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
        browser = p.chromium.launch(channel="msedge", headless=args.unattended)
        # タブを開き直してもログインが続くように、同じコンテキスト（Cookie の入れ物）からタブを作る
        context = browser.new_context()
        page = context.new_page()
        page.goto(BASE_URL + "/login/")
        if LOGIN_PATH in page.url:
            login(page, login_id, password)
        wait_until(send_at, "予約開始")
        if args.unattended and args.plan_id and auto_state(args.plan_id) != AUTO_RUNNING:
            raise SystemExit("待っている間に「予約係に任せる」が取り消されたため、予約しませんでした。")

        started_at = datetime.now(TOKYO)
        booked_room = None
        completed = False
        declined = False
        full_rooms = []
        problems = []  # 埋まっている以外の理由で予約できなかった部屋と、その理由
        for room in rooms:
            print(f"{room} を試しています…")
            room_members = members if room in NEEDS_MEMBERS else None
            room_teacher = teacher if room in TEACHER_ROOMS else None
            try:
                fill_until_confirm(
                    page,
                    add_url(event_id_of(room), args.date, args.start),
                    args.minutes,
                    members=room_members,
                    teacher=room_teacher,
                )
            except NotReached:
                print(f"  {room} は確認画面まで進めませんでした（埋まっている可能性があります）。")
                full_rooms.append(room)
                continue
            except Exception as e:
                # 画面が時間内に開かない等。この部屋はあきらめて、次の部屋を試す（例外の文面は入力値を含みうるので出さない）
                print(f"  {room} は画面が正しく開きませんでした（{type(e).__name__}）。次の部屋を試します。")
                problems.append(f"{room}：画面が開かなかった（{type(e).__name__}）")
                # 読み込みに失敗したタブで次の画面を開くと「割り込まれた」と失敗することがあるので、新しいタブに替える
                page.close()
                page = context.new_page()
                continue
            if not has_register_button(page):
                reason = page_reason(page)
                print(f"  {room} は確認画面に「登録」ボタンがありませんでした。画面の表示：{reason}")
                problems.append(f"{room}：確認画面に登録ボタンなし（{reason}）")
                if any(word in reason for word in LIMIT_WORDS):
                    print("  申し込み数が予約サイトの上限に達しているため、ほかの部屋は試しません。")
                    problems.append("申し込み数が上限のため、ほかの部屋は試さなかった")
                    break
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
        elif problems:
            result = "予約できなかった：" + "／".join(problems)
            if full_rooms:
                result += f"／ほか{len(full_rooms)}室は確認画面まで進めなかった"
            print("予約できませんでした。予約は送信していません。")
        else:
            result = f"空きなし（{len(full_rooms)}室とも確認画面まで進めなかった）"
            print(f"試した{len(full_rooms)}室とも予約できませんでした。予約は送信していません。")
        if args.plan_id:
            record_run(args.plan_id, started_at, result, full_rooms)
            if completed:
                mark_booked(args.plan_id, booked_room, by="自動")
                print("予定登録の画面で「予約完了」に切り替えました。")
        if not args.unattended:
            print("確認できたら、Edgeのウィンドウを閉じてください（閉じると終了します）。")
            page.wait_for_event("close", timeout=0)
        browser.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        if "--plan-id" in sys.argv and "--unattended" not in sys.argv:
            # 画面から別ウィンドウで起動したときは、結果を読めるように閉じる前に待つ
            input("\nEnter を押すと、このウィンドウを閉じます。")
