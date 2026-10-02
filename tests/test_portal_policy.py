import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from portal_policy import PORTALS, evaluate_application_safety, otp_is_eligible


class PortalPolicyTests(unittest.TestCase):
    def test_expected_portals_registered(self):
        for portal in ("linkedin", "naukri", "indeed", "wellfound", "glassdoor"):
            self.assertIn(portal, PORTALS)

    def test_live_disabled_blocks_submit_but_allows_safe_fill(self):
        result = evaluate_application_safety(live_submission_enabled=False)
        self.assertTrue(result.can_fill)
        self.assertFalse(result.can_submit)
        self.assertIn("live_submission_disabled", result.reasons)

    def test_unknown_required_field_blocks_submit(self):
        result = evaluate_application_safety(
            live_submission_enabled=True,
            unknown_required_fields=1,
        )
        self.assertTrue(result.can_fill)
        self.assertFalse(result.can_submit)
        self.assertIn("unknown_required_fields", result.reasons)

    def test_captcha_requires_human(self):
        result = evaluate_application_safety(
            live_submission_enabled=True,
            captcha_present=True,
        )
        self.assertFalse(result.can_fill)
        self.assertFalse(result.can_submit)
        self.assertIn("captcha_requires_human", result.reasons)

    def test_all_clear_can_submit_when_live_enabled(self):
        result = evaluate_application_safety(live_submission_enabled=True)
        self.assertTrue(result.can_fill)
        self.assertTrue(result.can_submit)
        self.assertEqual(result.reasons, ())

    def test_otp_must_be_recent_and_match_login_context(self):
        self.assertTrue(
            otp_is_eligible(
                sender_matches_portal=True,
                purpose_matches_login=True,
                age_seconds=60,
            )
        )
        self.assertFalse(
            otp_is_eligible(
                sender_matches_portal=True,
                purpose_matches_login=True,
                age_seconds=600,
            )
        )
        self.assertFalse(
            otp_is_eligible(
                sender_matches_portal=False,
                purpose_matches_login=True,
                age_seconds=30,
            )
        )


if __name__ == "__main__":
    unittest.main()
