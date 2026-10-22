"""予約状況の画面から、部屋の名前と番号の一覧を書き出す（予約の入力・送信はしない）。

  python list_rooms.py                … 本人1人用の保存場所のログイン情報で
  python list_rooms.py --user 友達    … その人のログイン情報で（コースによって見える部屋が違うかを調べる）

このアプリにまだ登録されていない部屋（rooms.py の ROOM_IDS にない部屋）と、番号が違う部屋も書き出す。
友達のログイン情報を使うときは、先に本人の了承をもらう。
"""

import argparse
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

import credentials
from auto_login import LOGIN_PATH, login
from reserve_dryrun import BASE_URL
from rooms import compare_room_options

RESULT_FILE = Path(__file__).parent / "rooms_result.txt"

COLLECT_OPTIONS_JS = """
() => [...document.querySelectorAll("select")].map((s) => ({
  name: s.getAttribute("name") || s.id || "",
  options: [...s.options].map((o) => `${o.value}=${o.textContent.trim()}`),
}))
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="予約状況の画面から、部屋の名前と番号の一覧を書き出す")
    parser.add_argument("--user", help="誰のログイン情報で開くか（省略すると、本人1人用の保存場所）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    login_id, password = credentials.load(args.user)
    lines: list[str] = [f"[ログインしたユーザー] {args.user or '（本人1人用の保存場所）'}"]
    room_options: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        page.goto(BASE_URL + "/login/")
        if LOGIN_PATH in page.url:
            login(page, login_id, password)
        page.goto(BASE_URL + "/reserve/calendar")
        page.wait_for_load_state("networkidle")

        for select in page.evaluate(COLLECT_OPTIONS_JS):
            if select["name"] in ("interval",):
                continue
            lines.append(f"[選択肢] {select['name']}")
            lines += [f"  {o}" for o in select["options"]]
            if select["name"] == "id":
                room_options = select["options"]
        event_ids = sorted(set(re.findall(r"event_id=(\d+)", page.content())), key=int)
        lines.append(f"[画面内の event_id] {', '.join(event_ids) or 'なし'}")
        browser.close()

    lines += compare_room_options(room_options)
    RESULT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n結果を {RESULT_FILE.name} に保存しました。予約は送信していません。")


if __name__ == "__main__":
    main()
