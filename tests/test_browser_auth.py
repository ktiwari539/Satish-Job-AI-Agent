import unittest
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from browser_auth import (
    BrowserAuthCredentials,
    execute_linkedin_auth,
    execute_linkedin_sign_in,
)


class FakeControl:
    def __init__(self):
        self.value = ""
        self.clicked = False

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def fill(self, value):
        self.value = value

    def click(self, timeout=0):
        self.clicked = True


class MissingControl:
    @property
    def first(self):
        return self

    def count(self):
        return 0


class FakeBody:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout=0):
        return self.text


class FakePage:
    def __init__(self, body="", url="https://www.linkedin.com/login"):
        self.url = url
        self.body = body
        self.username = FakeControl()
        self.password = FakeControl()
        self.submit = FakeControl()

    def goto(self, url, wait_until=None):
        self.url = url

    def locator(self, selector):
        if selector == "body":
            return FakeBody(self.body)
        if selector in ("#username", "input[name='session_key']", "input[autocomplete='username']", "input[type='email']"):
            return self.username
        if selector in ("#password", "input[name='session_password']", "input[autocomplete='current-password']", "input[type='password']"):
            return self.password
        if selector in ("button[type='submit']", "button:text-is('Sign in')", "button:has-text('Sign in')"):
            return self.submit
        return MissingControl()

    def wait_for_load_state(self, *args, **kwargs):
        pass

    def wait_for_timeout(self, value):
        pass


class BrowserAuthTests(unittest.TestCase):
    def test_existing_session_reuses_authentication(self):
        page = FakePage(url="https://www.linkedin.com/jobs/")
        result = execute_linkedin_auth(page, "SESSION_CONFIRMED")
        self.assertTrue(result.authenticated)
        self.assertEqual(result.action, "CONTINUE")

    def test_missing_credentials_fail_closed(self):
        page = FakePage()
        result = execute_linkedin_auth(page, "LOGIN_REQUIRED")
        self.assertFalse(result.authenticated)
        self.assertEqual(result.state, "BLOCKED")
        self.assertEqual(result.reason, "local_credentials_missing")

    def test_linkedin_sign_in_uses_local_credentials_and_verifies_session(self):
        page = FakePage(
            body="Jobs My Network Messaging Notifications Me",
            url="https://www.linkedin.com/login",
        )

        def after_click(timeout=0):
            page.submit.clicked = True
            page.url = "https://www.linkedin.com/feed/"

        page.submit.click = after_click
        credentials = BrowserAuthCredentials("candidate@example.com", "secret-value")

        result = execute_linkedin_sign_in(page, credentials)

        self.assertTrue(result.authenticated)
        self.assertEqual(result.state, "AUTHENTICATED")
        self.assertEqual(page.username.value, "candidate@example.com")
        self.assertEqual(page.password.value, "secret-value")

    def test_security_checkpoint_stops_after_sign_in(self):
        page = FakePage(
            body="Verify your identity Security verification",
            url="https://www.linkedin.com/login",
        )

        def after_click(timeout=0):
            page.url = "https://www.linkedin.com/checkpoint/challenge/"

        page.submit.click = after_click
        result = execute_linkedin_sign_in(
            page,
            BrowserAuthCredentials("candidate@example.com", "secret-value"),
        )

        self.assertEqual(result.state, "BLOCKED")
        self.assertFalse(result.authenticated)
        self.assertIn("checkpoint", result.reason)

    def test_account_not_found_requests_signup(self):
        page = FakePage(
            body="Couldn't find a LinkedIn account associated with this email.",
            url="https://www.linkedin.com/login",
        )
        result = execute_linkedin_sign_in(
            page,
            BrowserAuthCredentials("candidate@example.com", "secret-value"),
        )

        self.assertEqual(result.state, "SIGNUP_REQUIRED")
        self.assertEqual(result.action, "CREATE_ACCOUNT")


if __name__ == "__main__":
    unittest.main()
