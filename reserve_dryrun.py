"""段階2-3：予約内容を自動で入力し、確認画面で止める（練習モード）。

確認画面の「登録」ボタン（#register）は押さない。このファイルには押す処理そのものがない。

  python reserve_dryrun.py --room E312 --date 2026-10-28 --start 09:30 --minutes 60
"""

import argparse
from datetime import date, datetime, time
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import Page, sync_playwright

import credentials
from auto_login import ALLOWED_HOST, LOGIN_PATH, login
from booking_rules import DURATION_CHOICES_MIN, TOKYO, booking_opens_at, end_datetime, start_datetime
from notices import NOTICE_CHANGED, NOTICE_MISSING, notice_status
from rooms import NEEDS_MEMBERS, event_id_of, max_minutes, room_key

BASE_URL = f"https://{ALLOWED_HOST}/senzoku"
CONFIRM_PATH = "/senzoku/reserve/add_conf"
PAGE_TIMEOUT_MS = 15_000

# 予約画面の「ご利用時間」の選択肢の表示名
USETIME_LABELS = {30: "30分", 60: "1時間", 90: "1時間 30分", 120: "2時間", 150: "2時間 30分", 180: "3時間"}
DEFAULT_USE_TYPE = "個人練習"

NOT_REACHED_MESSAGE = (
    "確認画面まで進めませんでした。まだ予約できない日時か、その時間が埋まっている、"
    "または画面の作りが変わった可能性があります。Edgeの画面を確認してください。"
)


class NotReached(Exception):
    """その部屋では確認画面まで進めなかった（埋まっている等）。別の部屋なら進める可能性がある。"""


def add_url(event_id: int, use_date: date, start: time, base_url: str = BASE_URL) -> str:
    query = urlencode({"event_id": event_id, "date": use_date.isoformat(), "time": start.strftime("%H:%M")})
    return f"{base_url}/reserve/add?{query}"


def fill_until_confirm(
    page: Page, url: str, minutes: int, use_type: str = DEFAULT_USE_TYPE, members: list[str] | None = None
) -> None:
    """予約登録画面に入力して「確認」まで進む。確認画面の登録ボタンは押さない。

    members を渡したとき（E452）は、注意事項が承認済みの文面のままか確かめてから同意し、
    同時利用者の学籍番号を入力する。
    """
    page.goto(url)
    if urlsplit(page.url).hostname != urlsplit(url).hostname:
        raise SystemExit("予約サイト以外のページに移動したため、中止しました。")
    if members is not None:
        status, found = notice_status(page.inner_text("body"))
        if status == NOTICE_MISSING:
            # 予約登録の画面が出ていない（埋まっている・利用できない時間など）
            raise NotReached()
        if status == NOTICE_CHANGED:
            print("画面の注意事項：\n" + found.strip())
            raise SystemExit("注意事項の文面が、承認したものから変わっています。同意せずに中止しました。Edgeで文面を確認してください。")
    try:
        page.get_by_label(use_type, exact=True).check()
        if members is not None:
            page.check("#value_24")
            page.fill("#value_25", "\n".join(members))
        page.select_option("select[name='datetime[usetime]']", label=USETIME_LABELS[minutes])
        page.click("#conf")
        page.wait_for_url(lambda u: CONFIRM_PATH in u, timeout=PAGE_TIMEOUT_MS)
    except Exception:
        # 例外の文面に入力値が含まれる可能性があるので、そのまま表示しない
        raise NotReached() from None


def room_arg(room: str) -> str:
    try:
        return room_key(room)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="予約内容を入力し、確認画面で止める（練習モード）")
    parser.add_argument("--room", type=room_arg, required=True, help="部屋の名前（例：E312、E452）")
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="利用日（例：2026-10-28）")
    parser.add_argument("--start", type=time.fromisoformat, required=True, help="開始時刻（例：09:30）")
    parser.add_argument("--minutes", type=int, choices=DURATION_CHOICES_MIN, required=True, help="利用時間（分）")
    parser.add_argument("--use-type", default=DEFAULT_USE_TYPE, help="利用区分の表示名（初期値：個人練習）")
    return parser.parse_args()


def ask_members() -> list[str]:
    """同時利用者の学籍番号を入力してもらう（保存しない）。"""
    print("同時利用者の学籍番号を1人ずつ入力し、最後に何も入力せずに Enter を押してください。")
    members = []
    while line := input(f"{len(members) + 1}人目：").strip():
        members.append(line)
    if not members:
        raise SystemExit("この部屋は同時利用者の入力が必須です。中止しました。")
    return members


def main() -> None:
    args = parse_args()
    if args.minutes > max_minutes(args.room):
        raise SystemExit(f"この部屋の利用時間は{max_minutes(args.room)}分までです。")
    members = ask_members() if args.room in NEEDS_MEMBERS else None
    start_at = start_datetime(args.date, args.start)
    opens_at = booking_opens_at(end_datetime(start_at, args.minutes))
    if datetime.now(TOKYO) < opens_at:
        print(f"注意：予約可能日時（{opens_at:%Y-%m-%d %H:%M}）より前なので、確認画面まで進めない可能性があります。")

    login_id, password = credentials.load()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=False)
        page = browser.new_page()
        page.goto(BASE_URL + "/login/")
        if LOGIN_PATH in page.url:
            login(page, login_id, password)
        try:
            fill_until_confirm(page, add_url(event_id_of(args.room), args.date, args.start), args.minutes, args.use_type, members)
        except NotReached:
            raise SystemExit(NOT_REACHED_MESSAGE) from None
        print("確認画面まで進みました。予約はまだ完了していません（登録ボタンは押していません）。")
        print("Edgeで内容を確認したら、Edgeのウィンドウを閉じてください（閉じると終了します）。")
        page.wait_for_event("close", timeout=0)
        browser.close()


if __name__ == "__main__":
    main()
