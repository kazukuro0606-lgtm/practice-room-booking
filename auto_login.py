"""段階2-2：リザベーションエンジンに自動でログインする（予約の入力・送信はしない）。"""

from urllib.parse import urlsplit

from playwright.sync_api import Page, sync_playwright

import credentials
from open_site import load_url

# ログイン情報はこのサイトにだけ入力する
ALLOWED_HOST = "www4.revn.jp"
LOGIN_PATH = "/senzoku/login/"
LOGIN_TIMEOUT_MS = 15_000


def login(page: Page, login_id: str, password: str) -> None:
    if urlsplit(page.url).hostname != ALLOWED_HOST:
        raise SystemExit(f"{ALLOWED_HOST} 以外のページなので、ログイン情報を入力しません。")
    try:
        page.fill("#login_id", login_id)
        page.fill("#password", password)
        page.click("#login")
        page.wait_for_url(lambda url: LOGIN_PATH not in url, timeout=LOGIN_TIMEOUT_MS)
    except Exception:
        # 例外の文面に入力値が含まれる可能性があるので、そのまま表示しない
        raise SystemExit(
            "ログインできませんでした。ログインID・パスワードが正しいか、"
            "ログイン画面の作りが変わっていないかを確認してください。"
        ) from None


def main() -> None:
    url = load_url()
    login_id, password = credentials.load()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=False)
        page = browser.new_page()
        page.goto(url)
        if LOGIN_PATH in page.url:
            login(page, login_id, password)
        print(f"ログインできました：{page.title()}")
        print("確認できたら、Edgeのウィンドウを閉じてください（閉じると終了します）。")
        page.wait_for_event("close", timeout=0)
        browser.close()


if __name__ == "__main__":
    main()
