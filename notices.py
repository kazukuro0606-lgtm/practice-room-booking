"""予約画面の注意事項が、承認した文面から変わっていないかを確かめる（純粋な関数）。

注意事項「複数人利用 優先のお願い」は、注意事項のある部屋（rooms.NOTICE_ROOMS）で同じ文面。
自動で同意するのは、予定を登録した本人が画面でこの文面を承認しているとき（設定の approved_notices）だけ。
"""

import hashlib
import re

# 2026-10-21 に E452 の画面で確かめ、2026-10-22 に E215・E312・E412 などでも同じと確かめた注意事項
APPROVED_E452_NOTICE = (
    "「複数人利用 優先のお願い」を確認しました。"
    "【複数人利用 優先のお願い】"
    "利用用途が「個人練習」となっておりますが、この部屋は可能な限り「複数人」での利用を優先してください。"
    "個人での利用は極力控え、小練習室を利用するようご協力をお願いいたします。"
)

# 承認を記録するときの印。文面を変えると印も変わり、各自が承認し直すまでその部屋は使えなくなる
NOTICE_VERSION = "multi-priority-" + hashlib.sha256(APPROVED_E452_NOTICE.encode("utf-8")).hexdigest()[:12]

# 画面で承認してもらうときに見せる文面（予約サイトの表示どおり）
NOTICE_DISPLAY = (
    "【複数人利用 優先のお願い】\n"
    "利用用途が「個人練習」となっておりますが、この部屋は可能な限り「複数人」での利用を優先してください。\n"
    "個人での利用は極力控え、小練習室を利用するようご協力をお願いいたします。\n\n"
    "（確認の欄：「複数人利用 優先のお願い」を確認しました。）"
)

# 注意事項の前後にある項目名。注意事項の次に来る項目は画面によって違うため、最初に見つかったところまでを注意事項とする
E452_NOTICE_START = "利用用途について"
E452_NOTICE_ENDS = ("利用日時", "担当教員名", "同時利用者（学籍番号）")

# 画面の飾りや入力チェックの表示で、文面の一部ではないもの
_NOISE = ("必須", "｜", "|", "値を入力してください")


def normalize(text: str) -> str:
    for word in _NOISE:
        text = text.replace(word, "")
    return re.sub(r"\s+", "", text)


def extract_between(page_text: str, start: str, ends: tuple[str, ...]) -> str | None:
    """画面の文字列から、start と、その後で最初に現れる ends のいずれかとの間を取り出す。見つからなければ None。"""
    i = page_text.find(start)
    if i < 0:
        return None
    positions = [j for end in ends if (j := page_text.find(end, i + len(start))) >= 0]
    if not positions:
        return None
    return page_text[i + len(start) : min(positions)]


NOTICE_OK = "ok"
NOTICE_MISSING = "missing"  # 注意事項の欄が画面にない（予約登録の画面が出ていない等）
NOTICE_CHANGED = "changed"  # 注意事項の欄はあるが、文面が承認したものと違う


def notice_status(page_text: str) -> tuple[str, str]:
    """(状態, 画面で見つかった注意事項の文面) を返す。"""
    found = extract_between(page_text, E452_NOTICE_START, E452_NOTICE_ENDS)
    if found is None:
        return NOTICE_MISSING, ""
    if normalize(found) == normalize(APPROVED_E452_NOTICE):
        return NOTICE_OK, found
    return NOTICE_CHANGED, found


def notice_unchanged(page_text: str) -> bool:
    return notice_status(page_text)[0] == NOTICE_OK
