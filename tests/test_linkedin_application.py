import unittest
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from application_flow import ApplicationFlowResult
from apply_inspection import ApplicationEntryInspection
from linkedin_application import run_linkedin_application
from submission_engine import SubmissionResult


class LinkedInApplicationStateTests(unittest.TestCase):
    def test_verified_form_enters_application_form_stage(self):
        entry = ApplicationEntryInspection(
            application_type="LINKEDIN_EASY_APPLY",
            application_state="FORM_READY",
            opened=True,
            field_count=3,
        )
        with patch("linkedin_application.inspect_linkedin_application_entry", return_value=entry):
            result = run_linkedin_application(object(), open_easy_apply=True)

        self.assertEqual(result.engine_stage, "APPLICATION_FORM")
        self.assertEqual(
            result.engine_history,
            (
                "JOB_PAGE->APPLICATION_ENTRY:linkedin_easy_apply_entry_confirmed",
                "APPLICATION_ENTRY->APPLICATION_FORM:application_form_verified",
            ),
        )

    def test_entry_failure_blocks_without_fabricating_progress(self):
        entry = ApplicationEntryInspection(
            application_type="NO_APPLY_ENTRY_FOUND",
            application_state="APPLICATION_ENTRY_NOT_FOUND",
            reason="apply_button_not_detected_after_wait",
        )
        with patch("linkedin_application.inspect_linkedin_application_entry", return_value=entry):
            result = run_linkedin_application(object())

        self.assertEqual(result.engine_stage, "BLOCKED")
        self.assertEqual(len(result.engine_history), 1)
        self.assertIn("JOB_PAGE->BLOCKED", result.engine_history[0])

    def test_submit_ready_requires_review_stage_first(self):
        entry = ApplicationEntryInspection(
            application_type="LINKEDIN_EASY_APPLY",
            application_state="FORM_READY",
            opened=True,
        )
        flow = ApplicationFlowResult(state="SUBMIT_READY")
        with patch("linkedin_application.inspect_linkedin_application_entry", return_value=entry), patch(
            "linkedin_application.run_safe_application_flow", return_value=flow
        ):
            result = run_linkedin_application(
                object(),
                profile={"email": "candidate@example.com"},
                fill_application=True,
                advance_application=True,
            )

        self.assertEqual(result.engine_stage, "SUBMIT")
        self.assertEqual(
            result.engine_history[-2:],
            (
                "APPLICATION_FORM->REVIEW:review_stage_reached",
                "REVIEW->SUBMIT:submit_control_verified",
            ),
        )

    def test_no_transition_is_blocked_not_counted_as_progress(self):
        entry = ApplicationEntryInspection(
            application_type="LINKEDIN_EASY_APPLY",
            application_state="FORM_READY",
            opened=True,
        )
        flow = ApplicationFlowResult(
            state="NEXT_NO_TRANSITION",
            steps_completed=0,
            reasons=("easy_apply_progress_unchanged:1/4 pages",),
        )
        with patch("linkedin_application.inspect_linkedin_application_entry", return_value=entry), patch(
            "linkedin_application.run_safe_application_flow", return_value=flow
        ):
            result = run_linkedin_application(
                object(),
                profile={"email": "candidate@example.com"},
                fill_application=True,
                advance_application=True,
            )

        self.assertEqual(result.engine_stage, "BLOCKED")
        self.assertEqual(result.flow.steps_completed, 0)
        self.assertIn("APPLICATION_FORM->BLOCKED:next_no_transition", result.engine_history[-1])

    def test_confirmed_submit_reaches_completed_only_with_positive_evidence(self):
        entry = ApplicationEntryInspection(
            application_type="LINKEDIN_EASY_APPLY",
            application_state="FORM_READY",
            opened=True,
        )
        flow = ApplicationFlowResult(state="SUBMIT_READY")
        submission = SubmissionResult(
            state="CONFIRMED",
            confirmed=True,
            evidence="confirmation_dialog:Application submitted",
        )
        with patch("linkedin_application.inspect_linkedin_application_entry", return_value=entry), patch(
            "linkedin_application.run_safe_application_flow", return_value=flow
        ), patch(
            "linkedin_application.submit_linkedin_application", return_value=submission
        ):
            result = run_linkedin_application(
                object(),
                profile={"email": "candidate@example.com"},
                fill_application=True,
                advance_application=True,
                submit_application=True,
                live_submission_enabled=True,
            )

        self.assertEqual(result.engine_stage, "COMPLETED")
        self.assertTrue(result.submission.confirmed)
        self.assertEqual(
            result.engine_history[-2:],
            (
                "SUBMIT->CONFIRMATION:positive_submission_confirmation_detected",
                "CONFIRMATION->COMPLETED:submission_confirmed",
            ),
        )

    def test_unconfirmed_submit_blocks_and_never_completes(self):
        entry = ApplicationEntryInspection(
            application_type="LINKEDIN_EASY_APPLY",
            application_state="FORM_READY",
            opened=True,
        )
        flow = ApplicationFlowResult(state="SUBMIT_READY")
        submission = SubmissionResult(
            state="SUBMIT_UNCONFIRMED",
            confirmed=False,
            reason="confirmation_not_detected",
        )
        with patch("linkedin_application.inspect_linkedin_application_entry", return_value=entry), patch(
            "linkedin_application.run_safe_application_flow", return_value=flow
        ), patch(
            "linkedin_application.submit_linkedin_application", return_value=submission
        ):
            result = run_linkedin_application(
                object(),
                profile={"email": "candidate@example.com"},
                fill_application=True,
                advance_application=True,
                submit_application=True,
                live_submission_enabled=True,
            )

        self.assertEqual(result.engine_stage, "BLOCKED")
        self.assertFalse(result.submission.confirmed)
        self.assertNotIn("COMPLETED", "|".join(result.engine_history))


if __name__ == "__main__":
    unittest.main()
