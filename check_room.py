"""段階4b：まだ確かめていない部屋の予約登録画面を調べる（入力・送信はしない）。

  python check_room.py --date 2026-10-25 --start 09:00                  … 確かめていない部屋をすべて
  python check_room.py --date 2026-10-25 --start 09:00 --room E441 E442 … 指定した部屋だけ

部屋ごとに予約登録の画面を開き（Edgeは画面に出さない）、次を書き出す。何も入力せず、ボタンも押さない。
- 予約登録の画面が出たか（出ないときは、その日時が埋まっている・まだ予約できない等）
- 入力欄（ラジオボタン・チェックボックス・文字欄・選択肢）と、必須かどうか
- 選べる利用時間
- 申し込み欄の文字（注意事項など）。入力欄の中身は書き出さず、学籍番号など5桁以上の数字は *** で伏せる
結果は check_room_result.txt（Git対象外）にも保存する。--date と --start は、予約可能になっていて空いていそうな日時にする。
"""

import argparse
import re
from datetime import date, time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

import credentials
from auto_login import LOGIN_PATH, login
from inspect_page import COLLECT_JS
from reserve_dryrun import BASE_URL, add_url
from rooms import ROOM_IDS, VERIFIED_ROOMS, event_id_of, room_key, room_label

RESULT_FILE = Path(__file__).parent / "check_room_result.txt"
FORM_TAGS = ("select", "textarea")
FORM_TYPES = ("radio", "checkbox", "text", "number", "email", "tel")
# 申し込み欄には本人の学籍番号が表示されるため、5桁以上の数字の並びは伏せる
LONG_NUMBER = re.compile(r"\d{5,}")
# 申し込み欄の文字が長すぎるときは、ここまでで切る
MAX_FORM_TEXT = 2000


def unchecked_rooms() -> list[str]:
    return [r for r in ROOM_IDS if r not in VERIFIED_ROOMS]


def mask_numbers(text: str) -> str:
    return LONG_NUMBER.sub("***", text)


def form_lines(page: Page) -> list[str]:
    """予約登録の画面の入力欄と申し込み欄の文字を、書き出す行にする。"""
    if page.locator("#conf").count() == 0:
        return ["  予約登録の画面が出ませんでした（埋まっている・まだ予約できない日時の可能性があります）。"]
    lines = ["  [入力欄]"]
    for e in page.evaluate(COLLECT_JS):
        if not e["visible"]:
            continue
        if e["tag"] in FORM_TAGS or e["type"] in FORM_TYPES:
            parts = [f"{k}={e[k]}" for k in ("tag", "type", "id", "name", "label", "value", "required", "options") if e[k]]
            lines.append("    " + "  ".join(parts))
    usetime = page.locator("select[name='datetime[usetime]'] option").all_inner_texts()
    lines.append("  [利用時間の選択肢] " + " / ".join(t.strip() for t in usetime))
    form = page.locator("form:has(#conf)").first
    text = form.inner_text() if form.count() else page.inner_text("body")
    lines.append("  [申し込み欄の文字]")
    lines += ["    " + mask_numbers(line) for line in text[:MAX_FORM_TEXT].splitlines() if line.strip()]
    return lines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="まだ確かめていない部屋の予約登録画面を調べる（入力・送信はしない）")
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="調べる日（例：2026-10-25）")
    parser.add_argument("--start", type=time.fromisoformat, required=True, help="調べる開始時刻（例：09:00）")
    parser.add_argument("--room", nargs="*", type=room_key, help="調べる部屋（省略すると、確かめていない部屋をすべて）")
    parser.add_argument("--user", help="誰のログイン情報で開くか（省略すると、本人1人用の保存場所）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rooms = args.room or unchecked_rooms()
    login_id, password = credentials.load(args.user)
    lines = [f"調べた日時：{args.date} {args.start:%H:%M}"]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        page.goto(BASE_URL + "/login/")
        if LOGIN_PATH in page.url:
            login(page, login_id, password)
        for room in rooms:
            print(f"{room_label(room)} を調べています…")
            page.goto(add_url(event_id_of(room), args.date, args.start))
            lines.append(f"\n===== {room_label(room)} =====")
            lines += form_lines(page)
        browser.close()
    RESULT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n結果を {RESULT_FILE.name} に保存しました。予約は送信していません。")


if __name__ == "__main__":
    main()
