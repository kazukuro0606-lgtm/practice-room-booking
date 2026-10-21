"""予約画面の注意事項が、本人が承認した文面から変わっていないかを確かめる（純粋な関数）。"""

import re

# 2026-10-21 に本人が読んで、自動で同意してよいと承認した E452 の注意事項
APPROVED_E452_NOTICE = (
    "「複数人利用 優先のお願い」を確認しました。"
    "【複数人利用 優先のお願い】"
    "利用用途が「個人練習」となっておりますが、この部屋は可能な限り「複数人」での利用を優先してください。"
    "個人での利用は極力控え、小練習室を利用するようご協力をお願いいたします。"
)

# 注意事項の前後にある項目名
E452_NOTICE_START = "利用用途について"
E452_NOTICE_END = "同時利用者（学籍番号）"

# 画面の飾りや入力チェックの表示で、文面の一部ではないもの
_NOISE = ("必須", "｜", "|", "値を入力してください")


def normalize(text: str) -> str:
    for word in _NOISE:
        text = text.replace(word, "")
    return re.sub(r"\s+", "", text)


def extract_between(page_text: str, start: str, end: str) -> str | None:
    """画面の文字列から、start と end の間の部分を取り出す。見つからなければ None。"""
    i = page_text.find(start)
    if i < 0:
        return None
    j = page_text.find(end, i + len(start))
    if j < 0:
        return None
    return page_text[i + len(start) : j]


NOTICE_OK = "ok"
NOTICE_MISSING = "missing"  # 注意事項の欄が画面にない（予約登録の画面が出ていない等）
NOTICE_CHANGED = "changed"  # 注意事項の欄はあるが、文面が承認したものと違う


def notice_status(page_text: str) -> tuple[str, str]:
    """(状態, 画面で見つかった注意事項の文面) を返す。"""
    found = extract_between(page_text, E452_NOTICE_START, E452_NOTICE_END)
    if found is None:
        return NOTICE_MISSING, ""
    if normalize(found) == normalize(APPROVED_E452_NOTICE):
        return NOTICE_OK, found
    return NOTICE_CHANGED, found


def notice_unchanged(page_text: str) -> bool:
    return notice_status(page_text)[0] == NOTICE_OK
