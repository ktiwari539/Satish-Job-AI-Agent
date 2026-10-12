import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import naukri_google_setup as naukri


class Runtime:
    def __init__(self, config):
        self.config = config
        self.page = Mock()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class OTPSetupTests(unittest.TestCase):
    def test_manual_otp_flow_never_uses_google_oauth(self):
        unverified = {"status": "naukri_session_not_confirmed", "reason": "naukri_login_required"}
        verified = {"status": "naukri_session_verified"}
        with patch.object(naukri, "verify_naukri_session", side_effect=[unverified, verified]):
            with patch.object(naukri, "start_naukri_google_sign_in",
                              side_effect=AssertionError("Google sign-in forbidden")):
                result = naukri.setup_otp_session(
                    runtime_factory=Runtime, prompt=lambda _: "",
                    notify=lambda _: None,
                )
        self.assertEqual(result, verified)

    def test_otp_login_failure_never_claims_success(self):
        unverified = {"status": "naukri_session_not_confirmed", "reason": "naukri_login_required"}
        with patch.object(naukri, "verify_naukri_session", side_effect=[unverified, unverified]):
            result = naukri.setup_otp_session(
                runtime_factory=Runtime, prompt=lambda _: "", notify=lambda _: None
            )
        self.assertEqual(result["status"], "naukri_session_not_confirmed")

    def test_existing_verified_session_never_prompts(self):
        with patch.object(naukri, "verify_naukri_session",
                          return_value={"status": "naukri_session_verified"}):
            result = naukri.setup_otp_session(
                runtime_factory=Runtime,
                prompt=Mock(side_effect=AssertionError("unexpected prompt")),
                notify=lambda _: None,
            )
        self.assertEqual(result["status"], "naukri_session_verified")

    def test_cli_uses_otp_by_default(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["naukri_google_setup.py"]):
            with patch.object(naukri, "setup_otp_session",
                              return_value={"status": "naukri_session_verified"}) as otp:
                with patch.object(naukri, "setup_google_session",
                                  side_effect=AssertionError("Google OAuth forbidden")):
                    with redirect_stdout(output):
                        exit_code = naukri.main()
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "naukri_session_verified")
        otp.assert_called_once_with("browser-profile")


if __name__ == "__main__":
    unittest.main()
