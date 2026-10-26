"""Regression for a resume-selection radio misclassified as screening."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from unittest.mock import patch, MagicMock

from browser_form_runtime import inspect_page_fields


class ResumeChoiceRadioTest(unittest.TestCase):
    def test_resume_filename_radio_with_default_on_is_not_screening(self):
        page = MagicMock()
        page.evaluate.return_value = [
            {"key": "resume", "label": "Satish_Kumar_Tiwari_Resume.docx",
             "required": False, "field_type": "radio", "options": ["on"]},
            {"key": "experience", "label": "How many years of experience?",
             "required": True, "field_type": "text", "options": []},
        ]
        with patch("browser_form_runtime.trace_event") as trace:
            fields = inspect_page_fields(page)
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].key, "experience")
        trace.assert_called_once()
        self.assertEqual(trace.call_args.args[0],
                         "resume_choice_radio_excluded_from_screening")

    def test_real_screening_question_kept(self):
        page = MagicMock()
        page.evaluate.return_value = [
            {"key": "q1", "label": "Are you authorized to work here?",
             "required": True, "field_type": "radio", "options": ["Yes", "No"]},
        ]
        with patch("browser_form_runtime.trace_event") as trace:
            fields = inspect_page_fields(page)
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].field_type, "radio")
        trace.assert_not_called()

    def test_document_named_question_with_real_choices_is_preserved(self):
        page = MagicMock()
        page.evaluate.return_value = [
            {"key": "q2", "label": "Have you reviewed policy.pdf",
             "required": True, "field_type": "radio", "options": ["Yes", "No"]},
        ]
        with patch("browser_form_runtime.trace_event") as trace:
            fields = inspect_page_fields(page)
        self.assertEqual(len(fields), 1)
        trace.assert_not_called()


if __name__ == "__main__":
    unittest.main()
