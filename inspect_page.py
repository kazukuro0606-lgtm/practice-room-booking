"""段階2-2の準備：ログイン画面の入力欄とボタンの「名前」だけを書き出す。

入力された中身（value）・URLのクエリ・Cookie は書き出さない。
ログイン・入力・予約送信はしない。
"""

from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from open_site import load_url

RESULT_FILE = Path(__file__).parent / "inspect_result.txt"

# ページ内で実行し、要素の属性だけを集める（value は読まない）
COLLECT_JS = """
() => {
  const text = (s) => (s || "").replace(/\\s+/g, " ").trim().slice(0, 60);
  const labelOf = (el) => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return text(l.textContent);
    }
    const parent = el.closest("label");
    return parent ? text(parent.textContent) : "";
  };
  const selector = "input, select, textarea, button, [role=button], a[onclick], input[type=submit]";
  return [...document.querySelectorAll(selector)].map((el) => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute("type") || "",
    id: el.id || "",
    name: el.getAttribute("name") || "",
    placeholder: el.getAttribute("placeholder") || "",
    aria: el.getAttribute("aria-label") || "",
    label: labelOf(el),
    text: ["button", "a"].includes(el.tagName.toLowerCase()) ? text(el.textContent) : "",
    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
  }));
}
"""


def safe_url(url: str) -> str:
    """クエリやフラグメント（ログイン情報が入ることがある）を落とす。"""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def describe(frame_url: str, elements: list[dict]) -> list[str]:
    lines = [f"[フレーム] {safe_url(frame_url)}"]
    for e in elements:
        if not e["visible"] and e["type"] != "hidden":
            continue
        fields = [f"{k}={e[k]}" for k in ("tag", "type", "id", "name", "placeholder", "aria", "label", "text") if e[k]]
        lines.append("  " + "  ".join(fields))
    return lines


def main() -> None:
    url = load_url()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=False)
        page = browser.new_page()
        page.goto(url)
        print("Edgeでログイン画面を表示してください（学籍番号・パスワードは入力しないでください）。")
        input("表示できたら、このPowerShellに戻って Enter を押してください：")

        lines = [f"[ページ] {page.title()}  {safe_url(page.url)}"]
        for frame in page.frames:
            lines += describe(frame.url, frame.evaluate(COLLECT_JS))
        browser.close()

    RESULT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n結果を {RESULT_FILE.name} に保存しました。")


if __name__ == "__main__":
    main()
