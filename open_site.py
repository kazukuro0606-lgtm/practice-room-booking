"""段階2-1：予約ページをEdgeで開くだけ（ログイン・入力・予約送信はしない）。"""

import tomllib
from pathlib import Path

from playwright.sync_api import sync_playwright

SETTINGS_FILE = Path(__file__).parent / "local_settings.toml"


def load_url() -> str:
    if not SETTINGS_FILE.exists():
        raise SystemExit(
            "local_settings.toml がありません。local_settings.example.toml をコピーして作ってください。"
        )
    url = tomllib.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("url", "")
    if not url.startswith("https://") or "example.com" in url:
        raise SystemExit("local_settings.toml の url に、予約ページのアドレス（https://〜）を書いてください。")
    return url


def main() -> None:
    url = load_url()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=False)
        page = browser.new_page()
        page.goto(url)
        print(f"開いたページ：{page.title()}")
        print("確認できたら、Edgeのウィンドウを閉じてください（閉じると終了します）。")
        page.wait_for_event("close", timeout=0)
        browser.close()


if __name__ == "__main__":
    main()
