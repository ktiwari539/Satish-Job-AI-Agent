import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from application_forms import FormField, build_fill_plan, resolve_profile_key


class CustomApplicationAnswerTests(unittest.TestCase):
    def test_exact_custom_answer_is_used(self):
        fields = (
            FormField(
                key="q1",
                label="Flexible to work from office at Ghansoli, Navi Mumbai",
                required=True,
            ),
        )
        profile = {
            "answers": {
                "flexible to work from office at ghansoli, navi mumbai": "Yes",
            }
        }
        plan = build_fill_plan(fields, profile, live_submission_enabled=False)
        self.assertEqual(plan.values["q1"], "Yes")
        self.assertEqual(plan.unknown_required_fields, ())

    def test_known_numeric_application_fields_have_dedicated_keys(self):
        self.assertEqual(
            resolve_profile_key("Current Annual CTC (in INR)"),
            "current_ctc_inr",
        )
        self.assertEqual(
            resolve_profile_key("Expected Annual CTC (in INR)"),
            "expected_ctc_inr",
        )
        self.assertEqual(
            resolve_profile_key("Notice Period (in Days)"),
            "notice_period_days",
        )

    def test_unknown_question_still_fails_closed(self):
        fields = (FormField(key="q1", label="Unknown mandatory question", required=True),)
        plan = build_fill_plan(fields, {}, live_submission_enabled=False)
        self.assertEqual(plan.unknown_required_fields, ("Unknown mandatory question",))


if __name__ == "__main__":
    unittest.main()
