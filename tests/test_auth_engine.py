import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from auth_engine import can_use_email_otp, plan_authentication


class AuthEngineTests(unittest.TestCase):
    def test_existing_session_continues_without_login(self):
        plan = plan_authentication("SESSION_CONFIRMED")
        self.assertEqual(plan.stage, "AUTHENTICATED")
        self.assertEqual(plan.action, "CONTINUE")
        self.assertTrue(plan.can_continue)

    def test_login_required_plans_sign_in(self):
        plan = plan_authentication("LOGIN_REQUIRED")
        self.assertEqual(plan.stage, "LOGIN")
        self.assertEqual(plan.action, "SIGN_IN")
        self.assertFalse(plan.can_continue)

    def test_missing_account_plans_signup(self):
        plan = plan_authentication(
            "LOGIN_REQUIRED",
            account_missing=True,
            create_account_if_missing=True,
        )
        self.assertEqual(plan.stage, "SIGNUP")
        self.assertEqual(plan.action, "CREATE_ACCOUNT")

    def test_signup_email_verification_is_explicit_state(self):
        plan = plan_authentication(
            "LOGIN_REQUIRED",
            account_missing=True,
            email_verification_required=True,
        )
        self.assertEqual(plan.stage, "EMAIL_VERIFICATION")
        self.assertEqual(plan.action, "VERIFY_EMAIL")
        self.assertEqual(
            plan.history,
            (
                "SESSION_CHECK->SIGNUP:account_missing",
                "SIGNUP->EMAIL_VERIFICATION:signup_email_verification_required",
            ),
        )

    def test_security_challenge_always_stops(self):
        plan = plan_authentication("HUMAN_ACTION_REQUIRED")
        self.assertEqual(plan.stage, "BLOCKED")
        self.assertEqual(plan.action, "STOP")
        self.assertEqual(plan.reason, "security_challenge_requires_human")

    def test_unverified_session_fails_closed(self):
        plan = plan_authentication("SESSION_UNVERIFIED")
        self.assertEqual(plan.stage, "BLOCKED")
        self.assertEqual(plan.action, "STOP")

    def test_recent_matching_login_otp_is_eligible(self):
        self.assertTrue(
            can_use_email_otp(
                sender_matches_portal=True,
                purpose_matches_login=True,
                age_seconds=120,
            )
        )

    def test_wrong_purpose_or_old_otp_is_rejected(self):
        self.assertFalse(
            can_use_email_otp(
                sender_matches_portal=True,
                purpose_matches_login=False,
                age_seconds=30,
            )
        )
        self.assertFalse(
            can_use_email_otp(
                sender_matches_portal=True,
                purpose_matches_login=True,
                age_seconds=600,
            )
        )


if __name__ == "__main__":
    unittest.main()
