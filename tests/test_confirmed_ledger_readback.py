"""Exactly one positively confirmed, persisted application passes ledger readback."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from models import Job
from store import JobStore
from submission_engine import SubmissionResult, record_confirmed_submission


def example_job(job_id="4461542106"):
    return Job(
        source="linkedin", external_id=job_id,
        company="Firework", title="Sr. Customer Success Manager",
        location="India",
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        description="Customer success role. " * 12,
        required_skills=("customer success", "retention", "account management"),
    )


class LedgerReadbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(str(Path(self.tmp.name) / "job-agent.db"))
        self.job = example_job()

    def test_absent_or_unconfirmed_job_never_passes(self):
        self.assertIsNone(
            self.store.get_confirmed_submission("linkedin", "4461542106")
        )
        self.store.mark_applied(self.job, application_method="agent")
        self.assertIsNone(
            self.store.get_confirmed_submission("linkedin", "4461542106")
        )

    def test_positive_evidence_persisted_on_exact_job_passes(self):
        result = SubmissionResult(
            state="CONFIRMED", confirmed=True,
            evidence="confirmation_dialog:Application submitted",
        )
        self.assertTrue(record_confirmed_submission(self.store, self.job, result))
        row = self.store.get_confirmed_submission("linkedin", "4461542106")
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "CONFIRMED")
        self.assertEqual(row["application_method"], "agent")
        self.assertTrue(row["applied_at"])
        self.assertIsNone(
            self.store.get_confirmed_submission("linkedin", "4476701830")
        )
        self.assertIsNone(
            self.store.get_confirmed_submission("naukri", "4461542106")
        )

    def test_manual_or_note_free_rows_are_not_agent_confirmed(self):
        self.store.mark_submission_confirmed(
            self.job, application_method="manual",
            note="manual application",
        )
        self.assertIsNone(
            self.store.get_confirmed_submission("linkedin", "4461542106")
        )
        self.store.mark_submission_confirmed(
            self.job, application_method="agent", note=""
        )
        self.assertIsNone(
            self.store.get_confirmed_submission("linkedin", "4461542106")
        )


if __name__ == "__main__":
    unittest.main()
