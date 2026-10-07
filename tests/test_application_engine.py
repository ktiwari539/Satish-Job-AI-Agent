import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from application_engine import (
    ApplicationStage,
    ApplicationStateMachine,
    InvalidApplicationTransition,
)
from question_resolver import resolve_application_answer


class ApplicationEngineTests(unittest.TestCase):
    def test_valid_end_to_end_state_path(self):
        machine = ApplicationStateMachine()
        path = (
            ApplicationStage.AUTH,
            ApplicationStage.APPLICATION_ENTRY,
            ApplicationStage.APPLICATION_FORM,
            ApplicationStage.SCREENING,
            ApplicationStage.RESUME,
            ApplicationStage.REVIEW,
            ApplicationStage.SUBMIT,
            ApplicationStage.CONFIRMATION,
            ApplicationStage.COMPLETED,
        )
        for stage in path:
            machine.transition(stage)
        self.assertEqual(machine.stage, ApplicationStage.COMPLETED)
        self.assertEqual(len(machine.history), len(path))

    def test_submit_cannot_skip_review(self):
        machine = ApplicationStateMachine()
        machine.transition(ApplicationStage.APPLICATION_ENTRY)
        machine.transition(ApplicationStage.APPLICATION_FORM)
        with self.assertRaises(InvalidApplicationTransition):
            machine.transition(ApplicationStage.SUBMIT)

    def test_click_is_not_implicitly_a_transition(self):
        machine = ApplicationStateMachine(ApplicationStage.APPLICATION_FORM)
        self.assertEqual(machine.stage, ApplicationStage.APPLICATION_FORM)
        self.assertEqual(machine.history, ())


class QuestionResolverTests(unittest.TestCase):
    def test_resolves_verified_profile_fact(self):
        profile = {"experience_years": 8.1}
        result = resolve_application_answer("Total experience *", profile)
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual(result.answer, "8.1")
        self.assertEqual(result.source, "profile:experience_years")

    def test_resolves_custom_answer_before_alias(self):
        profile = {
            "gender": "Male",
            "answers": {"gender": "I do not wish to self-identify"},
        }
        result = resolve_application_answer(
            "Gender",
            profile,
            options=("Male", "Female", "I do not wish to self-identify"),
        )
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual(result.answer, "I do not wish to self-identify")
        self.assertEqual(result.source, "custom_answer")

    def test_unknown_eeo_uses_decline_when_available(self):
        result = resolve_application_answer(
            "Disability status",
            {},
            options=("Yes", "No", "I do not wish to self-identify"),
        )
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual(result.answer, "I do not wish to self-identify")
        self.assertEqual(result.source, "eeo_decline_fallback")

    def test_unknown_required_question_fails_closed(self):
        result = resolve_application_answer(
            "What is your favorite database?",
            {},
            required=True,
        )
        self.assertEqual(result.status, "UNKNOWN_REQUIRED")
        self.assertEqual(result.reason, "no_verified_answer")

    def test_stored_value_must_match_select_options(self):
        profile = {"employment_type": "Permanent"}
        result = resolve_application_answer(
            "Employment type",
            profile,
            options=("Contract", "Temporary"),
        )
        self.assertEqual(result.status, "UNKNOWN_REQUIRED")
        self.assertIn("employment_type", result.reason)


if __name__ == "__main__":
    unittest.main()
