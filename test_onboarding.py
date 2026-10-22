import unittest

from onboarding import PAGES


class OnboardingTest(unittest.TestCase):
    def test_page_count_in_welcome_matches(self):
        # 最初のページに書いた「全Nページ」が、実際のページ数と合っている
        self.assertIn(f"全{len(PAGES)}ページ", PAGES[0][1])

    def test_pages_have_title_and_body(self):
        for title, body in PAGES:
            self.assertTrue(title.strip())
            self.assertTrue(body.strip())


if __name__ == "__main__":
    unittest.main()
