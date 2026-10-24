"""Applicant-approved answers must persist locally and never be invented."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from answer_learning import learn_required_answers
from browser_form_runtime import BrowserFieldSnapshot
from question_resolver import resolve_application_answer
from application_forms import build_fill_plan, FormField


class AnswerLearningTests(unittest.TestCase):
    def test_interactive_missing_question_is_learned_and_reused(self):
        q = "Are you willing to work rotating shifts?"
        field = BrowserFieldSnapshot(
            "shiftChoices", q, True, "radio", ("Yes", "No")
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private_profile.json"
            path.write_text('{"answers": {}}')
            profile = {"answers": {}}
            with patch("answer_learning.inspect_page_fields", return_value=(field,)), \
                 patch("builtins.input", return_value="No"), \
                 redirect_stdout(io.StringIO()) as out:
                result = learn_required_answers(
                    MagicMock(), profile, str(path), (q,)
                )
            self.assertEqual(result["answers_saved"], 1)
            self.assertEqual(json.loads(path.read_text())["answers"][q], "No")
            self.assertEqual(profile["answers"][q], "No")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            # This answer is reusable in the normal field planner.
            planned = build_fill_plan(
                (FormField("shiftChoices", q, True, "radio", ("Yes", "No")),),
                profile, live_submission_enabled=False,
            )
            self.assertEqual(planned.values["shiftChoices"], "No")
            self.assertNotIn("unknown_required_fields", planned.reasons)
            self.assertNotIn("No", str(result))
            self.assertIn("Required question", out.getvalue())

    def test_rejects_invalid_option_without_persisting(self):
        q = "Are you willing to travel for this fictional role?"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private_profile.json"
            path.write_text('{"answers": {}}')
            with patch("answer_learning.inspect_page_fields", return_value=(
                BrowserFieldSnapshot("travel", q, True, "radio", ("Yes", "No")),
            )), patch("builtins.input", return_value="Maybe"), \
                 redirect_stdout(io.StringIO()):
                result = learn_required_answers(
                    MagicMock(), {"answers": {}}, str(path), (q,)
                )
            self.assertEqual(result["answers_saved"], 0)
            self.assertEqual(json.loads(path.read_text())["answers"], {})

    def test_missing_fact_does_not_generate_negative_answer(self):
        q = "Do you have minimum 10 years of overall experience?"
        result = resolve_application_answer(
            q, {}, options=("Yes", "No"), required=True,
        )
        self.assertEqual(result.status, "UNKNOWN_REQUIRED")

    def test_verified_experience_threshold_can_answer_no_or_yes(self):
        q = "Do you have minimum 10 years of overall experience?"
        for experience, expected in (("8", "No"), ("12", "Yes")):
            with self.subTest(experience=experience):
                result = resolve_application_answer(
                    q, {"experience_years": experience},
                    options=("Yes", "No"), required=True,
                )
                self.assertEqual(result.status, "RESOLVED")
                self.assertEqual(result.answer, expected)

    def test_strict_experience_threshold_does_not_overstate_years(self):
        question = "Do you have more than 10 years of overall experience?"
        for years, expected in (("9", "No"), ("10", "No"), ("11", "Yes")):
            with self.subTest(years=years):
                answer = resolve_application_answer(
                    question, {"experience_years": years},
                    options=("Yes", "No"),
                )
                self.assertEqual(answer.status, "RESOLVED")
                self.assertEqual(answer.answer, expected)

    def test_industry_specific_experience_is_not_inferred(self):
        q = "Do you have min 10 years of BPO experience?"
        result = resolve_application_answer(
            q, {"experience_years": "20"},
            options=("Yes", "No"),
        )
        self.assertEqual(result.status, "UNKNOWN_REQUIRED")

    def test_stored_answer_fills_canonical_field_when_scalar_missing(self):
        field = FormField(
            "Experience", "Years of experience", True, "text"
        )
        plan = build_fill_plan(
            (field,),
            {"answers": {"Years of experience": "8"}},
        )
        self.assertEqual(plan.values["Experience"], "8")
        self.assertFalse(plan.missing_profile_values)


if __name__ == "__main__":
    unittest.main()
