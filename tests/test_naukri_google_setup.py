import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naukri_google_setup import setup_google_session, verify_naukri_session


class FakeSession:
    def __init__(self, config):
        self.config = config
        self.page = object()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True


class NaukriGoogleSetupTests(unittest.TestCase):
    def test_existing_session_reused_without_google_prompt(self):
        prompt = Mock(side_effect=AssertionError("should not prompt"))
        result = {"status": "naukri_session_verified"}
        with patch("naukri_google_setup.verify_naukri_session", return_value=result) as verify:
            actual = setup_google_session(prompt=prompt, runtime_factory=FakeSession)
        self.assertEqual(actual, result)
        verify.assert_called_once()
        prompt.assert_not_called()

    def test_google_sign_in_is_human_controlled_then_session_verified(self):
        states = [
            {"status": "naukri_session_not_confirmed", "reason": "naukri_login_required"},
            {"status": "naukri_session_verified"},
        ]
        prompt = Mock(return_value="")
        with patch("naukri_google_setup.verify_naukri_session", side_effect=states) as verify:
            actual = setup_google_session(prompt=prompt, runtime_factory=FakeSession)
        self.assertEqual(actual["status"], "naukri_session_verified")
        prompt.assert_called_once()
        self.assertEqual(verify.call_count, 2)

    def test_google_sign_in_unverified_never_claims_success(self):
        with patch(
            "naukri_google_setup.verify_naukri_session",
            side_effect=[
                {"status": "naukri_session_not_confirmed", "reason": "naukri_login_required"},
                {"status": "naukri_session_not_confirmed", "reason": "naukri_login_required"},
            ],
        ):
            actual = setup_google_session(prompt=lambda _: "", runtime_factory=FakeSession)
        self.assertEqual(actual["status"], "naukri_session_not_confirmed")

    def test_security_challenge_stops_without_prompt(self):
        prompt = Mock(side_effect=AssertionError("should not prompt"))
        with patch(
            "naukri_google_setup.verify_naukri_session",
            return_value={"status": "human_action_required", "reason": "naukri_security_challenge"},
        ):
            actual = setup_google_session(prompt=prompt, runtime_factory=FakeSession)
        self.assertEqual(actual["status"], "human_action_required")
        prompt.assert_not_called()

    def test_runtime_uses_existing_agent_browser_profile(self):
        created = []
        def factory(config):
            created.append(config)
            return FakeSession(config)
        with patch(
            "naukri_google_setup.verify_naukri_session",
            return_value={"status": "naukri_session_verified"},
        ):
            setup_google_session(profile_dir="browser-profile", runtime_factory=factory)
        self.assertEqual(created[0].user_data_dir, "browser-profile")
        self.assertFalse(created[0].headless)


if __name__ == "__main__":
    unittest.main()
