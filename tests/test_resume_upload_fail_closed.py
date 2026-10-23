"""Resume upload must never silently succeed when LinkedIn removed the input."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from application_forms import FillPlan
from browser_form_runtime import apply_fill_plan
from application_flow import run_safe_application_flow


class Collection:
    def __init__(self, count=0):
        self._count = count
        self.first = self
        self.uploaded = []
    def count(self):
        return self._count
    def set_input_files(self, path):
        self.uploaded.append(path)
    def inner_text(self, timeout=0):
        return ""
    def is_visible(self):
        return False
    def is_enabled(self):
        return False


class Page:
    url = "https://www.linkedin.com/jobs/view/4461542106/"
    def __init__(self, file_count):
        self.file_input = Collection(file_count)
    def locator(self, selector):
        return self.file_input if selector == 'input[type="file"]' else Collection()
    def evaluate(self, script, *args):
        return None


class ResumeUploadSafetyTests(unittest.TestCase):
    def test_required_resume_input_not_found_blocks_flow(self):
        page = Page(0)
        plan = FillPlan(can_fill=True, resume_path="/tmp/candidate.docx")
        with patch("application_flow.build_page_fill_plan", return_value=plan), \
             patch("application_flow.trace_event"), \
             patch("application_flow.inspect_easy_apply_state"):
            result = run_safe_application_flow(
                page, {}, resume_path=plan.resume_path,
                advance=True, live_submission_enabled=True,
            )
        self.assertEqual(result.state, "BLOCKED_AFTER_FILL")
        self.assertIn("resume_upload_input_not_found", result.reasons)
        self.assertNotIn("resume_uploaded", result.actions)

    def test_required_resume_input_uploads_and_records_action(self):
        page = Page(1)
        plan = FillPlan(can_fill=True, resume_path="/tmp/candidate.docx")
        with patch("application_flow.build_page_fill_plan", return_value=plan), \
             patch("application_flow.trace_event"), \
             patch("application_flow.inspect_easy_apply_state"), \
             patch("application_flow._visible_action", return_value=(None, "")), \
             patch("application_flow._progress_scoped_next", return_value=(None, "")):
            result = run_safe_application_flow(
                page, {}, resume_path=plan.resume_path,
                advance=True, live_submission_enabled=True,
            )
        self.assertEqual(page.file_input.uploaded, ["/tmp/candidate.docx"])
        self.assertIn("resume_file_input_set", result.actions)

    def test_no_new_upload_requested_is_not_falsely_reported_as_uploaded(self):
        page = Page(0)
        plan = FillPlan(can_fill=True, resume_path="")
        self.assertEqual(apply_fill_plan(page, plan), ())
        self.assertFalse(page.file_input.uploaded)


if __name__ == "__main__":
    unittest.main()
