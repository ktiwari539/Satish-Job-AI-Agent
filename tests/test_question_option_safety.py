import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from question_resolver import match_answer_to_option, resolve_application_answer


class QuestionOptionSafetyTests(unittest.TestCase):
    def test_male_never_matches_female(self):
        self.assertEqual(
            match_answer_to_option("Male", ("Female", "Male", "Prefer not to say")),
            "Male",
        )

    def test_missing_male_option_fails_closed(self):
        self.assertEqual(
            match_answer_to_option("Male", ("Female", "Prefer not to say")),
            "",
        )

    def test_boolean_answer_matches_explanatory_option(self):
        self.assertEqual(
            match_answer_to_option(
                "Yes",
                ("No, I do not require sponsorship", "Yes, I require sponsorship"),
            ),
            "Yes, I require sponsorship",
        )

    def test_ambiguous_boolean_options_fail_closed(self):
        self.assertEqual(
            match_answer_to_option("Yes", ("Yes - option A", "Yes - option B", "No")),
            "",
        )

    def test_numeric_experience_matches_year_option(self):
        self.assertEqual(
            match_answer_to_option("7", ("5 years", "7 years", "10 years")),
            "7 years",
        )

    def test_resolver_uses_observed_options(self):
        result = resolve_application_answer(
            "Gender",
            {"gender": "Male"},
            options=("Female", "Male", "Prefer not to say"),
            required=True,
        )
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual(result.answer, "Male")


if __name__ == "__main__":
    unittest.main()
