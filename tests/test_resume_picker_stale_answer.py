"""A verified resume picker must not reapply stale radio answer-bank values."""
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from application_flow import run_safe_application_flow
from browser_form_runtime import BrowserFieldSnapshot
from application_forms import FillPlan

class ResumePickerStaleAnswerTests(unittest.TestCase):
    def test_stale_radio_mapping_is_not_passed_to_filler(self):
        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/4468935961/"
        page.evaluate.return_value = True
        plan = FillPlan(values={"resume_choice": "on"}, can_fill=True,
                        reasons=("live_submission_disabled",))
        with patch("application_flow.answer_verified_screening_groups"), \
             patch("application_flow.apply_approved_yes_no_answers", return_value={
                  "present":0, "confirmed":0}), \
             patch("application_flow.build_page_fill_plan", return_value=plan), \
             patch("application_flow.inspect_page_fields", return_value=(
                  BrowserFieldSnapshot("resume_choice","Resume.docx",False,"radio",("on",)),
             )), \
             patch("application_flow.apply_fill_plan", return_value=(
                  "live_submission_disabled",)) as fill, \
             patch("application_flow.inspect_easy_apply_state"), \
             patch("application_flow._blocking_confirmation_dialog", return_value=""), \
             patch("application_flow.inspect_resume_evidence", return_value="matching_resume_selected"), \
             patch("application_flow._visible_action", return_value=(None,"")), \
             patch("application_flow._next_control", return_value=(None,"")) if False else patch("application_flow.trace_event"):
            run_safe_application_flow(page, {}, resume_path="/tmp/resume.docx",
                                      verified_easy_apply_modal=True,
                                      advance=False, max_steps=1)
        self.assertTrue(fill.called)
        self.assertNotIn("resume_choice", fill.call_args.args[1].values)

if __name__ == "__main__":
    unittest.main()
