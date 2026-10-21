"""段階2-3の準備：予約画面の入力欄・ボタン・リンクの「名前」だけを画面ごとに書き出す。

ログインは自動で行う。画面を進めるのは本人で、予約の最終ボタンは押さない。
入力された中身（value）・Cookie は書き出さず、URLの秘密らしい値は伏せる。
"""

import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from playwright.sync_api import sync_playwright

import credentials
from auto_login import LOGIN_PATH, login
from open_site import load_url

RESULT_FILE = Path(__file__).parent / "inspect_result.txt"

# この名前を含むURLパラメータの値は伏せる
SECRET_PARAM = re.compile(r"token|session|sid|csrf|auth|key|pass|login|user|mail", re.IGNORECASE)

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
  const selector = "input, select, textarea, button, [role=button], a[href], [onclick]";
  return [...document.querySelectorAll(selector)].map((el) => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute("type") || "",
    id: el.id || "",
    name: el.getAttribute("name") || "",
    class: text(el.getAttribute("class")),
    placeholder: el.getAttribute("placeholder") || "",
    aria: el.getAttribute("aria-label") || "",
    label: labelOf(el),
    text: ["input", "select", "textarea"].includes(el.tagName.toLowerCase()) ? "" : text(el.textContent),
    href: el.getAttribute("href") || "",
    onclick: text(el.getAttribute("onclick")),
    // 選択肢の値はサイトが決めた固定値なので記録する（入力欄の中身は読まない）
    value: ["checkbox", "radio"].includes(el.type) ? text(el.getAttribute("value")) : "",
    required: el.required || el.getAttribute("aria-required") === "true" ? "yes" : "",
    options: el.tagName === "SELECT" ? [...el.options].slice(0, 15).map((o) => text(o.textContent)).join(" / ") : "",
    visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
  }));
}
"""

FIELDS = ("tag", "type", "id", "name", "class", "placeholder", "aria", "label", "text", "href", "onclick", "value", "required", "options")


def safe_url(url: str) -> str:
    """フラグメントを落とし、秘密らしいパラメータの値を *** にする。"""
    parts = urlsplit(url)
    query = [(k, "***" if SECRET_PARAM.search(k) else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)]
    base = f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.scheme else parts.path
    return f"{base}?{urlencode(query, safe='*')}" if query else base


def describe(frame_url: str, elements: list[dict]) -> list[str]:
    lines = [f"[フレーム] {safe_url(frame_url)}"]
    for e in elements:
        if not e["visible"] and e["type"] != "hidden":
            continue
        e = {**e, "href": safe_url(e["href"]) if e["href"] and not e["href"].startswith("javascript:") else e["href"]}
        lines.append("  " + "  ".join(f"{k}={e[k]}" for k in FIELDS if e[k]))
    return lines


def main() -> None:
    url = load_url()
    login_id, password = credentials.load()
    lines: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url)
        if LOGIN_PATH in page.url:
            login(page, login_id, password)
        print("ログインしました。")
        print("予約の画面を1つずつ進め、画面ごとにこのPowerShellで Enter を押してください。")
        print("※ 最後の「予約する」「申し込む」などのボタンは押さないでください。")

        count = 0
        while True:
            answer = input(f"\n画面{count + 1}を記録するなら Enter、終わるなら q と入力して Enter：")
            if answer.strip().lower() == "q":
                break
            page = context.pages[-1]  # 新しいタブが開いた場合は、いちばん新しいタブを調べる
            count += 1
            lines.append(f"\n===== 画面{count} =====")
            lines.append(f"[ページ] {page.title()}  {safe_url(page.url)}")
            for frame in page.frames:
                lines += describe(frame.url, frame.evaluate(COLLECT_JS))
            RESULT_FILE.write_text("\n".join(lines), encoding="utf-8")
            print(f"画面{count}を記録しました（{page.title()}）。")
        browser.close()

    print(f"\n{count}画面分の結果を {RESULT_FILE.name} に保存しました。")


if __name__ == "__main__":
    main()
