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

    def test_custom_answer_normalization_preserves_legacy_keys(self):
        fields = (FormField("q1", "Can you work in Mumbai?", True),)
        profile = {"answers": {"can you work in mumbai?": "Yes"}}
        plan = build_fill_plan(fields, profile)
        self.assertEqual(plan.values["q1"], "Yes")

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

    def test_superset_exact_live_screening_questions(self):
        fields = (
            FormField("q1", "How many years of experience do you have with Customer Success?", True),
            FormField("q2", "What is your current CTC?", True),
            FormField("q3", "What is your expected CTC?", True),
            FormField("q4", "What is your notice period?", True),
        )
        profile = {
            "customer_success_years": "7",
            "current_ctc": "12.5 LPA",
            "expected_ctc": "19 LPA",
            "notice_period": "30 days",
        }
        plan = build_fill_plan(fields, profile, live_submission_enabled=True)
        self.assertEqual(plan.values, {
            "q1": "7",
            "q2": "12.5 LPA",
            "q3": "19 LPA",
            "q4": "30 days",
        })
        self.assertEqual(plan.unknown_required_fields, ())
        self.assertEqual(plan.missing_profile_values, ())
        self.assertTrue(plan.can_submit)

    def test_semantic_punctuation_variants_still_resolve(self):
        profile = {
            "customer_success_years": "7",
            "current_ctc": "12.5 LPA",
            "expected_ctc": "19 LPA",
            "notice_period": "30 days",
        }
        fields = (
            FormField("q1", "Customer Success Experience (years) *", True),
            FormField("q2", "Current CTC (LPA) *", True),
            FormField("q3", "Expected CTC (LPA) *", True),
            FormField("q4", "Notice period *", True),
        )
        plan = build_fill_plan(fields, profile, live_submission_enabled=True)
        self.assertIn("q4", plan.values)
        self.assertEqual(plan.values['q1'],'7')
        self.assertEqual(plan.values['q2'],'12.5')
        self.assertEqual(plan.values['q3'],'19')
        self.assertEqual(plan.unknown_required_fields,())
        self.assertTrue(plan.can_submit)

    def test_unknown_question_still_fails_closed(self):
        fields = (FormField(key="q1", label="Unknown mandatory question", required=True),)
        plan = build_fill_plan(fields, {}, live_submission_enabled=False)
        self.assertEqual(plan.unknown_required_fields, ("Unknown mandatory question",))


if __name__ == "__main__":
    unittest.main()
