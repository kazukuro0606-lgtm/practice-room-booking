"""予約状況の画面から、部屋の名前と番号の一覧を書き出す（予約の入力・送信はしない）。"""

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

import credentials
from auto_login import LOGIN_PATH, login
from reserve_dryrun import BASE_URL

RESULT_FILE = Path(__file__).parent / "rooms_result.txt"

COLLECT_OPTIONS_JS = """
() => [...document.querySelectorAll("select")].map((s) => ({
  name: s.getAttribute("name") || s.id || "",
  options: [...s.options].map((o) => `${o.value}=${o.textContent.trim()}`),
}))
"""


def main() -> None:
    login_id, password = credentials.load()
    lines: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=False)
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
        event_ids = sorted(set(re.findall(r"event_id=(\d+)", page.content())), key=int)
        lines.append(f"[画面内の event_id] {', '.join(event_ids) or 'なし'}")
        browser.close()

    RESULT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n結果を {RESULT_FILE.name} に保存しました。")


if __name__ == "__main__":
    main()
