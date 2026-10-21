import unittest

from notices import notice_unchanged

# 2026-10-21 に本人が画面からコピーした文字列
PAGE_TEXT = """予約登録
利用用途について
必須
「複数人利用 優先のお願い」を確認しました。

｜
【複数人利用 優先のお願い】
利用用途が「個人練習」となっておりますが、この部屋は可能な限り「複数人」での利用を優先してください。
個人での利用は極力控え、小練習室を利用するようご協力をお願いいたします。
値を入力してください
同時利用者（学籍番号）
必須
"""


class NoticesTest(unittest.TestCase):
    def test_approved_text_matches(self):
        self.assertTrue(notice_unchanged(PAGE_TEXT))

    def test_changed_text_is_rejected(self):
        changed = PAGE_TEXT.replace("極力控え", "禁止とし")
        self.assertFalse(notice_unchanged(changed))

    def test_added_sentence_is_rejected(self):
        added = PAGE_TEXT.replace("お願いいたします。", "お願いいたします。\n違反した場合は利用停止とします。")
        self.assertFalse(notice_unchanged(added))

    def test_missing_section_is_rejected(self):
        self.assertFalse(notice_unchanged("予約登録\n同時利用者（学籍番号）"))


if __name__ == "__main__":
    unittest.main()
