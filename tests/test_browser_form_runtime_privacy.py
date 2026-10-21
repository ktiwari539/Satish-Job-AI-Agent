"""Live application trace must not persist resume names or account details."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from application_forms import FillPlan
from browser_form_runtime import BrowserFieldSnapshot, build_page_fill_plan


class FakePage:
    def locator(self, name):
        if name == "body":
            return SimpleNamespace(inner_text=lambda timeout=0: "Apply to Example 2/4 pages")
        return SimpleNamespace(count=lambda: 0)


class BrowserFormTracePrivacyTests(unittest.TestCase):
    def test_snapshot_logs_metadata_not_labels_resume_filenames_or_email(self):
        fields = (
            BrowserFieldSnapshot("email_key", "private-user@example.com", True, "select-one",
                                 ("private-user@example.com",)),
            BrowserFieldSnapshot("resume_key", "private-resume-document.docx", False, "radio",
                                 ("private-resume-document.docx",)),
        )
        with patch("browser_form_runtime.inspect_page_fields", return_value=fields), \
             patch("browser_form_runtime.inspect_form_snapshot",
                   return_value=SimpleNamespace(captcha_present=False, manual_auth_required=False)), \
             patch("browser_form_runtime.build_fill_plan",
                   return_value=FillPlan(can_fill=True)), \
             patch("browser_form_runtime.trace_event") as trace:
            build_page_fill_plan(FakePage(), {}, live_submission_enabled=True)

        trace.assert_called_once()
        self.assertEqual(trace.call_args.args[0], "form_snapshot")
        kwargs = trace.call_args.kwargs
        self.assertEqual(kwargs["field_count"], 2)
        self.assertEqual(kwargs["fields"][0]["option_count"], 1)
        for field in kwargs["fields"]:
            self.assertNotIn("label", field)
            self.assertNotIn("key", field)
            self.assertNotIn("options", field)
        self.assertNotIn("private-user@example.com", str(kwargs))
        self.assertNotIn("private-resume-document.docx", str(kwargs))


if __name__ == "__main__":
    unittest.main()
