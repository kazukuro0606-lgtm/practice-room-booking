"""予約サイトのアカウントを確かめる（予約係 scheduler.py が、確認待ちの人ごとに起動する。予約は送信しない）。

  python account_check.py --user ユーザー名

1. その人のログインIDとパスワードでログインできるか
2. その人に見える部屋（予約状況の画面の部屋の選択肢。見える部屋＝その人が使ってよい部屋）
3. 見える部屋のうち、このアプリに未登録の部屋の予約画面の作り（管理者が見て、部屋を登録するか決める）
結果は account_checks.py で data/account_checks/ユーザー名.json に保存する。Edge は画面に出さない。
"""

import argparse
from datetime import datetime, time, timedelta

from playwright.sync_api import Page, sync_playwright

import credentials
from account_checks import STATUS_ERROR, STATUS_LOGIN_FAILED, STATUS_OK, record_result
from auto_login import LOGIN_PATH, login
from booking_rules import TOKYO
from check_room import form_lines
from list_rooms import COLLECT_OPTIONS_JS
from reserve_dryrun import BASE_URL, add_url
from rooms import ROOM_IDS, ROOM_OPTION

# try_login の結果
LOGIN_OK = "ok"
LOGIN_WRONG = "wrong"  # ログインできなかった（ログインIDかパスワードが違う可能性が高い）
LOGIN_UNREACHABLE = "unreachable"  # 予約サイトやEdgeを開けなかった（入力値の正しさは分からない）


def try_login(login_id: str, password: str, base_url: str = BASE_URL) -> str:
    """入力されたログインIDとパスワードで予約サイトにログインできるかだけを確かめる（保存する前に使う）。"""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            try:
                page = browser.new_page()
                page.goto(base_url + "/login/")
                if LOGIN_PATH not in page.url or not page.locator("#login_id").count():
                    return LOGIN_UNREACHABLE
                try:
                    login(page, login_id, password)
                except SystemExit:
                    return LOGIN_WRONG
                return LOGIN_OK
            finally:
                browser.close()
    except Exception:
        # 例外の文面に入力値が含まれる可能性があるので、中身は使わない
        return LOGIN_UNREACHABLE


# 未登録の部屋の予約画面を開くときに試す時刻（埋まっていると画面が出ないので、いくつか試す）
PROBE_TIMES = (time(9, 0), time(13, 0), time(17, 0))


def visible_room_ids(page: Page) -> dict[str, int]:
    """予約状況の画面の部屋の選択肢から、その人に見える部屋と番号を取り出す。"""
    page.goto(BASE_URL + "/reserve/calendar")
    page.wait_for_load_state("networkidle")
    for select in page.evaluate(COLLECT_OPTIONS_JS):
        if select["name"] == "id":
            return {m.group(2): int(m.group(1)) for o in select["options"] if (m := ROOM_OPTION.match(o))}
    return {}


def probe_room(page: Page, event_id: int, now: datetime) -> list[str]:
    """未登録の部屋の予約画面の作りを書き出す（何も入力せず、ボタンも押さない）。"""
    day = (now + timedelta(days=1)).date()
    for start in PROBE_TIMES:
        page.goto(add_url(event_id, day, start))
        if page.locator("#conf").count():
            return [f"調べた日時：{day} {start:%H:%M}"] + form_lines(page)
    return ["予約登録の画面が出ませんでした（調べた時刻がすべて埋まっていた可能性があります）"]


def main() -> None:
    parser = argparse.ArgumentParser(description="予約サイトのアカウントを確かめる（予約は送信しない）")
    parser.add_argument("--user", required=True)
    args = parser.parse_args()
    now = datetime.now(TOKYO)
    try:
        login_id, password = credentials.load(args.user)
    except SystemExit:
        record_result(args.user, now, STATUS_ERROR, message="予約サイトのログイン情報が保存されていません")
        raise
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        try:
            page.goto(BASE_URL + "/login/")
            if LOGIN_PATH in page.url:
                try:
                    login(page, login_id, password)
                except SystemExit:
                    record_result(args.user, now, STATUS_LOGIN_FAILED, message="ログインIDかパスワードが違う可能性があります")
                    print("ログインできませんでした。")
                    return
            visible = visible_room_ids(page)
            if not visible:
                record_result(args.user, now, STATUS_ERROR, message="予約状況の画面で部屋の一覧が見つかりませんでした")
                print("部屋の一覧が見つかりませんでした。")
                return
            unknown = {}
            for room, event_id in visible.items():
                if room not in ROOM_IDS:
                    print(f"アプリに未登録の部屋 {room}（番号 {event_id}）を調べています…")
                    unknown[room] = {"event_id": event_id, "report": probe_room(page, event_id, now)}
            record_result(args.user, now, STATUS_OK, visible=visible, unknown=unknown)
            print(f"ログインできました。見える部屋：{len(visible)}室（アプリに未登録：{len(unknown)}室）")
        except Exception as e:
            # 例外の文面に入力値が含まれる可能性があるので、記録するのは種類だけ
            record_result(args.user, now, STATUS_ERROR, message=f"予約サイトを確かめられませんでした（{type(e).__name__}）")
            raise
        finally:
            browser.close()


if __name__ == "__main__":
    main()
