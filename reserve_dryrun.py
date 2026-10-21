"""段階2-3：予約内容を自動で入力し、確認画面で止める（練習モード）。

確認画面の「登録」ボタン（#register）は押さない。このファイルには押す処理そのものがない。

  python reserve_dryrun.py --event-id 159 --date 2026-10-28 --start 09:30 --minutes 60
"""

import argparse
from datetime import date, datetime, time
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import Page, sync_playwright

import credentials
from auto_login import ALLOWED_HOST, LOGIN_PATH, login
from booking_rules import DURATION_CHOICES_MIN, TOKYO, booking_opens_at, end_datetime, start_datetime

BASE_URL = f"https://{ALLOWED_HOST}/senzoku"
CONFIRM_PATH = "/senzoku/reserve/add_conf"
PAGE_TIMEOUT_MS = 15_000

# 予約画面の「ご利用時間」の選択肢の表示名
USETIME_LABELS = {30: "30分", 60: "1時間", 90: "1時間 30分"}
USE_TYPE_LABEL = "個人練習"


def add_url(event_id: int, use_date: date, start: time, base_url: str = BASE_URL) -> str:
    query = urlencode({"event_id": event_id, "date": use_date.isoformat(), "time": start.strftime("%H:%M")})
    return f"{base_url}/reserve/add?{query}"


def fill_until_confirm(page: Page, url: str, minutes: int) -> None:
    """予約登録画面に入力して「確認」まで進む。確認画面の登録ボタンは押さない。"""
    page.goto(url)
    if urlsplit(page.url).hostname != urlsplit(url).hostname:
        raise SystemExit("予約サイト以外のページに移動したため、中止しました。")
    try:
        page.get_by_label(USE_TYPE_LABEL, exact=True).check()
        page.select_option("select[name='datetime[usetime]']", label=USETIME_LABELS[minutes])
        page.click("#conf")
        page.wait_for_url(lambda u: CONFIRM_PATH in u, timeout=PAGE_TIMEOUT_MS)
    except Exception:
        raise SystemExit(
            "確認画面まで進めませんでした。まだ予約できない日時か、その時間が埋まっている、"
            "または画面の作りが変わった可能性があります。Edgeの画面を確認してください。"
        ) from None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="予約内容を入力し、確認画面で止める（練習モード）")
    parser.add_argument("--event-id", type=int, required=True, help="部屋の番号（予約画面のアドレスの event_id）")
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="利用日（例：2026-10-28）")
    parser.add_argument("--start", type=time.fromisoformat, required=True, help="開始時刻（例：09:30）")
    parser.add_argument("--minutes", type=int, choices=DURATION_CHOICES_MIN, required=True, help="利用時間（分）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
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
        fill_until_confirm(page, add_url(args.event_id, args.date, args.start), args.minutes)
        print("確認画面まで進みました。予約はまだ完了していません（登録ボタンは押していません）。")
        print("Edgeで内容を確認したら、Edgeのウィンドウを閉じてください（閉じると終了します）。")
        page.wait_for_event("close", timeout=0)
        browser.close()


if __name__ == "__main__":
    main()
