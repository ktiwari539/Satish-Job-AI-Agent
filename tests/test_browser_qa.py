import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from browser_qa import classify_generic_session


class BrowserQATests(unittest.TestCase):
    def test_generic_login_page(self):
        result = classify_generic_session(
            "indeed",
            "https://example.invalid/account/login",
            "Email address Password Sign in",
        )
        self.assertEqual(result.status, "LOGIN_REQUIRED")

    def test_generic_security_challenge(self):
        result = classify_generic_session(
            "foundit",
            "https://example.invalid/",
            "Please verify you are human",
        )
        self.assertEqual(result.status, "HUMAN_ACTION_REQUIRED")

    def test_generic_session_confirmed(self):
        result = classify_generic_session(
            "wellfound",
            "https://example.invalid/jobs",
            "My profile Account settings Jobs",
        )
        self.assertEqual(result.status, "SESSION_CONFIRMED")

    def test_generic_ambiguous_fails_closed(self):
        result = classify_generic_session(
            "glassdoor",
            "https://example.invalid/jobs",
            "Browse jobs",
        )
        self.assertEqual(result.status, "SESSION_UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
