"""No employer screening answer is generated, logged, or clicked without an approved profile fact."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from approved_screening_choices import (
    apply_approved_yes_no_answers, _CHOICE_SCRIPT,
)
from application_flow import run_safe_application_flow


Q1 = "Do you have min 10+ years of overall experience, preferably with significant experience in operations/team management?"
Q2 = "Do you have strong background in BPO, Insurance, Telesales, Sales Operations or Healthcare Operations?"
Q3 = "Are you currently residing in Zirakpur , or are you willing to relocate to Zirakpur for this opportunity?"


class ApprovedScreeningChoiceTests(unittest.TestCase):
    def test_three_private_no_answers_are_passed_in_memory_not_to_logs(self):
        profile = {"answers": {Q1: "No", Q2: "No", Q3: "No"}}
        page = MagicMock()
        page.evaluate.return_value = {
            "present": 3, "confirmed": 3, "ambiguous": 0,
            "unverified": 0, "missing_controls": 0,
        }
        result = apply_approved_yes_no_answers(page, profile)
        self.assertEqual(result["confirmed"], 3)
        js, payload = page.evaluate.call_args.args
        self.assertEqual(js, _CHOICE_SCRIPT)
        self.assertEqual(len(payload), 3)
        self.assertTrue(all(item["answer"] == "no" for item in payload))
        self.assertNotIn(Q1, str(result))
        self.assertNotIn("No", str(result))

    def test_missing_answers_do_not_touch_browser(self):
        page = MagicMock()
        result = apply_approved_yes_no_answers(page, {})
        page.evaluate.assert_not_called()
        self.assertEqual(result["present"], 0)

    def test_unapproved_or_non_boolean_answers_do_not_select(self):
        page = MagicMock()
        result = apply_approved_yes_no_answers(page, {
            "answers": {"What is your desired salary?": "500000"}
        })
        self.assertEqual(result["confirmed"], 0)
        page.evaluate.assert_not_called()

    def test_selection_disconnect_fails_closed(self):
        page = MagicMock()
        page.evaluate.side_effect = RuntimeError("Connection closed")
        result = apply_approved_yes_no_answers(page, {"answers": {Q1: "No"}})
        self.assertEqual(result["unverified"], 1)
        self.assertEqual(result["confirmed"], 0)

    def test_ambiguous_selection_blocks_before_form_fill(self):
        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/4481663953/"
        page.evaluate.return_value = True
        status = {"present": 3, "confirmed": 2, "ambiguous": 1,
                  "unverified": 0, "missing_controls": 0}
        with patch("application_flow.inspect_easy_apply_state"), \
             patch("application_flow._blocking_confirmation_dialog", return_value=""), \
             patch("application_flow.apply_approved_yes_no_answers", return_value=status), \
             patch("application_flow.build_page_fill_plan") as plan, \
             patch("application_flow.trace_event") as trace:
            result = run_safe_application_flow(
                page, {"answers": {Q1: "No", Q2: "No", Q3: "No"}},
                verified_easy_apply_modal=True, advance=True,
                inspect_review=True, live_submission_enabled=False,
            )
        self.assertEqual(result.state, "BLOCKED_APPROVED_SCREENING_SELECTION")
        plan.assert_not_called()
        event = next(call.kwargs for call in trace.call_args_list
                     if call.args[0] == "approved_screening_answer_selection")
        self.assertEqual(event["confirmed"], 2)
        self.assertFalse(event["answer_text_logged"])
        self.assertFalse(event["question_text_logged"])


if __name__ == "__main__":
    unittest.main()
