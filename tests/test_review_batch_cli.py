import unittest
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from application_flow import ApplicationFlowResult
from apply_inspection import ApplicationEntryInspection
from linkedin_application import LinkedInApplicationRun
from models import Job
from review_batch_cli import _prepare_linkedin


class FakePage:
    def __init__(self):
        self.url = ""

    def goto(self, url, wait_until=None):
        self.url = url


class ReviewBatchCLITests(unittest.TestCase):
    def test_linkedin_review_preparation_opens_safe_external_apply(self):
        entry = ApplicationEntryInspection(
            application_type="EXTERNAL_APPLY",
            application_state="FORM_READY",
            ats_provider="greenhouse",
            opened=True,
        )
        flow = ApplicationFlowResult(
            state="REVIEW_INSPECTED",
            review_mismatches=(),
        )
        run = LinkedInApplicationRun(entry=entry, flow=flow)
        job = Job(
            "linkedin",
            "1",
            "Example",
            "Customer Success Manager",
            "India",
            "https://linkedin.invalid/1",
            "full description",
        )

        with patch("review_batch_cli.run_linkedin_application", return_value=run) as mocked:
            prepare = _prepare_linkedin(FakePage(), {}, "/tmp/resume.pdf")
            result = prepare(job, {"email": "candidate@example.invalid"})

        self.assertEqual(result.state, "READY_FOR_REVIEW")
        kwargs = mocked.call_args.kwargs
        self.assertTrue(kwargs["open_easy_apply"])
        self.assertTrue(kwargs["open_external_apply"])
        self.assertTrue(kwargs["fill_application"])
        self.assertTrue(kwargs["advance_application"])
        self.assertTrue(kwargs["inspect_review"])
        self.assertFalse(kwargs["submit_application"])
        self.assertFalse(kwargs["live_submission_enabled"])

    def test_no_flow_reports_application_type_and_state(self):
        entry = ApplicationEntryInspection(
            application_type="EXTERNAL_APPLY",
            application_state="APPLICATION_ENTRY_FOUND",
            reason="entry_not_opened",
        )
        run = LinkedInApplicationRun(entry=entry, flow=None)
        job = Job(
            "linkedin",
            "2",
            "Example",
            "Customer Success Manager",
            "India",
            "https://linkedin.invalid/2",
            "full description",
        )

        with patch("review_batch_cli.run_linkedin_application", return_value=run):
            prepare = _prepare_linkedin(FakePage(), {}, "/tmp/resume.pdf")
            result = prepare(job, {})

        self.assertEqual(result.state, "BLOCKED")
        self.assertIn("EXTERNAL_APPLY", result.reason)
        self.assertIn("APPLICATION_ENTRY_FOUND", result.reason)


if __name__ == "__main__":
    unittest.main()
