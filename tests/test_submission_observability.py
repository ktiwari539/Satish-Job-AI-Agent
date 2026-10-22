"""Uncertain LinkedIn clicks remain unconfirmed while trace shows actual action."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from submission_engine import (
    detect_linkedin_submission_confirmation, submit_linkedin_application,
)


class FakePage:
    url = "https://www.linkedin.com/jobs/view/4461542106/"
    def evaluate(self, source):
        self.source = source
        return ""


class SubmissionObservabilityTests(unittest.TestCase):
    def test_confirmation_detector_inspects_visible_toast_and_status_not_body(self):
        page = FakePage()
        result = detect_linkedin_submission_confirmation(page)
        self.assertEqual(result, "")
        self.assertIn('[role="status"]', page.source)
        self.assertIn('.artdeco-toast-item', page.source)
        self.assertIn('visible_success_notification:application_sent', page.source)

    def test_unconfirmed_click_emits_action_without_falsely_recording_success(self):
        page = FakePage()
        button = Mock()
        button.inner_text.return_value = "Submit application"
        button.get_attribute.return_value = None
        with patch("submission_engine._active_dialog_root", return_value=""), \
             patch("submission_engine._verified_inline_linkedin_final_review",
                   return_value=True), \
             patch("submission_engine._visible_submit_control",
                   return_value=(button, "Submit application")), \
             patch("submission_engine._wait_for_linkedin_confirmation",
                   return_value=""), \
             patch("submission_engine.trace_event") as trace:
            result = submit_linkedin_application(
                page, live_submission_enabled=True, prior_state="SUBMIT_READY"
            )
        self.assertEqual(result.state, "SUBMIT_UNCONFIRMED")
        self.assertFalse(result.confirmed)
        button.click.assert_called_once()
        events = [call.args[0] for call in trace.call_args_list]
        self.assertIn("submission_click_completed", events)
        self.assertIn("submission_confirmation_checked", events)
        self.assertFalse(trace.call_args.kwargs["positive_evidence"])

    def test_no_live_approval_does_not_emit_completed_click_event(self):
        page = FakePage()
        with patch("submission_engine.trace_event") as trace, \
             patch("submission_engine._visible_submit_control") as button:
            result = submit_linkedin_application(
                page, live_submission_enabled=False, prior_state="SUBMIT_READY"
            )
        self.assertEqual(result.state, "SUBMIT_DISABLED")
        button.assert_not_called()
        trace.assert_not_called()


if __name__ == "__main__":
    unittest.main()
