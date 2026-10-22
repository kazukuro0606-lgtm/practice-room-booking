"""予約状況の画面の「タグから絞り込み」のピアノの種類ごとに、出てくる部屋を書き出す（予約の入力・送信はしない）。

  python piano_rooms.py                … 本人1人用の保存場所のログイン情報で
  python piano_rooms.py --user 友達    … その人のログイン情報で（コースによって見える部屋が違う）

タグを1つずつ押して、表に出てくる部屋の名前を集める。タグの作り（押す前後の HTML）と URL も書き出す
（5桁以上の数字は *** で伏せる）。友達のログイン情報を使うときは、先に本人の了承をもらう。
"""

import argparse
import re
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

import credentials
from auto_login import LOGIN_PATH, login
from check_room import mask_numbers
from inspect_page import safe_url
from reserve_dryrun import BASE_URL

RESULT_FILE = Path(__file__).parent / "piano_result.txt"
PIANO_TAGS = ("グランドピアノ", "アップライトピアノ", "ピアノなし", "電子ピアノ")
ROOM_NAME = re.compile(r"[A-Z]{1,3}\d{2,4}室")

# 画面に見えている要素のうち、その要素自身の文字が部屋の名前だけのもの（表の見出しなど）。
# 選択肢（select）や、隠れている説明の中の部屋の名前は数えない
ROOMS_JS = """
() => [...document.querySelectorAll("body *")]
  .filter((e) => !e.closest("select")
    && (e.offsetWidth || e.offsetHeight || e.getClientRects().length)
    && getComputedStyle(e).visibility !== "hidden")
  .map((e) => [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join("").trim())
  .filter((t) => /^[A-Z]{1,3}\\d{2,4}室/.test(t))
"""

# その要素自身の文字（子要素の文字を含まない）にタグの文字を含む要素。タグ以外（部屋の説明など）に同じ言葉があるかも見る
MATCHES_JS = """
(label) => [...document.querySelectorAll("body *")]
  .filter((e) => [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.includes(label)))
  .slice(0, 6)
  .map((e) => {
    const box = e.closest("a, button, label, li") || e;
    const input = box.querySelector("input") || (box.getAttribute("for") && document.getElementById(box.getAttribute("for")));
    return {
      visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length),
      checked: input ? input.checked : null,
      html: box.outerHTML.slice(0, 300),
    };
  })
"""

# 「タグから絞り込み」の欄（その中だけでタグを押す）
TAG_PANEL = ":is(div, section, form, ul, dl, fieldset):has-text('タグから絞り込み'):has-text('ピアノなし')"


def rooms_on_page(page: Page) -> list[str]:
    seen: list[str] = []
    for text in page.evaluate(ROOMS_JS):
        name = ROOM_NAME.match(text).group(0)
        if name not in seen:
            seen.append(name)
    return seen


def open_calendar(page: Page) -> None:
    page.goto(BASE_URL + "/reserve/calendar")
    page.wait_for_load_state("networkidle")


def tag_info(page: Page, label: str) -> str:
    matches = page.evaluate(MATCHES_JS, label)
    if not matches:
        return "（見つからない）"
    lines = [f"{len(matches)}か所（最大6）"]
    for m in matches:
        lines.append(f"    - 見える={m['visible']} checked={m['checked']} html={m['html']}")
    return mask_numbers("\n".join(lines))


def click_tag(page: Page, label: str) -> None:
    panel = page.locator(TAG_PANEL).last  # いちばん内側の欄
    if not panel.is_visible():
        # 欄が閉じているときは「タグから絞り込み」を押して開く
        page.get_by_text("タグから絞り込み").first.click()
        page.wait_for_timeout(800)
    panel.get_by_text(label).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2500)  # 絞り込みが画面の中だけで行われる場合に備えて少し待つ


def main() -> None:
    parser = argparse.ArgumentParser(description="ピアノの種類ごとに、予約状況の画面に出てくる部屋を書き出す")
    parser.add_argument("--user", help="誰のログイン情報で開くか（省略すると、本人1人用の保存場所）")
    args = parser.parse_args()
    login_id, password = credentials.load(args.user)
    lines: list[str] = [f"[ログインしたユーザー] {args.user or '（本人1人用の保存場所）'}"]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        page.goto(BASE_URL + "/login/")
        if LOGIN_PATH in page.url:
            login(page, login_id, password)

        open_calendar(page)
        lines.append(f"[絞り込み前] URL={safe_url(page.url)}")
        for label in PIANO_TAGS:
            lines.append(f"  タグ {label}：{tag_info(page, label)}")
        all_rooms = rooms_on_page(page)
        lines.append(f"  出ている部屋（{len(all_rooms)}室）：{', '.join(all_rooms) or 'なし'}")

        for label in PIANO_TAGS:
            open_calendar(page)
            lines.append(f"[{label}]")
            try:
                click_tag(page, label)
            except Exception as e:
                lines.append(f"  押せませんでした（{type(e).__name__}）")
                continue
            rooms = rooms_on_page(page)
            lines.append(f"  押した後の URL={safe_url(page.url)}")
            lines.append(f"  押した後のタグ：{tag_info(page, label)}")
            lines.append(f"  出ている部屋（{len(rooms)}室）：{', '.join(rooms) or 'なし'}")
            try:
                click_tag(page, label)  # 押す前の状態に戻す（予約サイトが絞り込みを覚えている場合のため）
                lines.append(f"  もう一度押して戻した後のタグ：{tag_info(page, label)}")
            except Exception as e:
                lines.append(f"  戻せませんでした（{type(e).__name__}）")
        browser.close()

    RESULT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n結果を {RESULT_FILE.name} に保存しました。予約は送信していません。")


if __name__ == "__main__":
    main()
