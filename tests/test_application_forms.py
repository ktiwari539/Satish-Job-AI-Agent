import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from application_forms import FormField, build_fill_plan, resolve_profile_key


PROFILE = {
    "full_name": "Test User",
    "email": "test@example.invalid",
    "phone": "9999999999",
    "location": "India",
    "linkedin": "https://example.invalid/profile",
    "notice_period": "30 days",
    "experience_years": "8",
}


class ApplicationFormTests(unittest.TestCase):
    def test_known_fields_map_to_profile(self):
        fields = (
            FormField("name", "Full Name", True),
            FormField("email", "Email Address", True),
            FormField("phone", "Mobile Number", True),
        )
        plan = build_fill_plan(fields, PROFILE)
        self.assertTrue(plan.can_fill)
        self.assertEqual(plan.values["name"], "Test User")
        self.assertFalse(plan.can_submit)
        self.assertIn("live_submission_disabled", plan.reasons)

    def test_unknown_required_field_blocks_submit(self):
        fields = (
            FormField("name", "Full Name", True),
            FormField("motivation", "Why do you want to work here?", True),
        )
        plan = build_fill_plan(fields, PROFILE, live_submission_enabled=True)
        self.assertIn("Why do you want to work here?", plan.unknown_required_fields)
        self.assertFalse(plan.can_submit)

    def test_missing_required_profile_value_blocks_fill(self):
        fields = (FormField("salary", "Expected Compensation", True),)
        plan = build_fill_plan(fields, PROFILE, live_submission_enabled=True)
        self.assertIn("expected_ctc", plan.missing_profile_values)
        self.assertFalse(plan.can_fill)

    def test_verified_answer_bank_resolves_known_screening_question(self):
        profile = dict(PROFILE)
        profile["people_management_years"] = 7
        fields = (
            FormField("management", "People management experience", True),
        )
        plan = build_fill_plan(fields, profile)
        self.assertEqual(plan.values["management"], "7")
        self.assertNotIn("People management experience", plan.unknown_required_fields)

    def test_verified_demographic_answer_is_used_when_present(self):
        profile = dict(PROFILE)
        profile["gender"] = "Male"
        fields = (FormField("gender", "Gender", True),)
        plan = build_fill_plan(fields, profile)
        self.assertEqual(plan.values["gender"], "Male")
        self.assertEqual(plan.unknown_required_fields, ())

    def test_direct_profile_value_must_match_observed_options(self):
        profile = dict(PROFILE)
        profile["notice_period"] = "30 days"
        fields = (
            FormField(
                "notice",
                "Notice Period",
                True,
                "select",
                ("Immediate", "30 days", "60 days"),
            ),
        )
        plan = build_fill_plan(fields, profile)
        self.assertEqual(plan.values["notice"], "30 days")
        self.assertEqual(plan.unknown_required_fields, ())

    def test_direct_profile_value_fails_closed_when_option_missing(self):
        profile = dict(PROFILE)
        profile["notice_period"] = "30 days"
        fields = (
            FormField(
                "notice",
                "Notice Period",
                True,
                "select",
                ("Immediate", "60 days", "90 days"),
            ),
        )
        plan = build_fill_plan(fields, profile, live_submission_enabled=True)
        self.assertNotIn("notice", plan.values)
        self.assertIn("Notice Period", plan.unknown_required_fields)
        self.assertFalse(plan.can_submit)

    def test_resume_is_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            resume = Path(tmp) / "resume.pdf"
            resume.write_bytes(b"%PDF-test")
            fields = (FormField("resume", "Resume", True, "file"),)
            plan = build_fill_plan(fields, PROFILE, resume_path=str(resume))
            self.assertEqual(plan.resume_path, str(resume))
            self.assertTrue(plan.can_fill)

    def test_captcha_hard_stops_fill(self):
        fields = (FormField("name", "Full Name", True),)
        plan = build_fill_plan(
            fields,
            PROFILE,
            captcha_present=True,
            live_submission_enabled=True,
        )
        self.assertFalse(plan.can_fill)
        self.assertIn("captcha_requires_human", plan.reasons)

    def test_alias_resolution(self):
        self.assertEqual(resolve_profile_key("Current Salary"), "current_ctc")
        self.assertEqual(resolve_profile_key("Years of Experience"), "experience_years")


if __name__ == "__main__":
    unittest.main()
