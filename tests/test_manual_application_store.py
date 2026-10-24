import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models import Job
from store import JobStore


class ManualApplicationStoreTests(unittest.TestCase):
    def test_manual_application_marks_job_seen_and_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "jobs.db")
            store = JobStore(db)
            job = Job(
                source="linkedin",
                external_id="4470567267",
                company="Hexaware Technologies",
                title="Assistant Manager - Inbound Customer Support Operations",
                location="Navi Mumbai",
                url="https://www.linkedin.com/jobs/view/4470567267/",
                description="",
            )
            store.mark_applied(job, application_method="manual")
            self.assertTrue(store.is_seen(job))
            self.assertTrue(store.is_applied(job))

    def test_portal_verified_exact_job_stays_duplicate_even_after_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            job = Job(
                source="linkedin", external_id="4461542106", company="Firework",
                title="Sr. Customer Success Manager", location="",
                url="https://www.linkedin.com/jobs/view/4461542106/",
                description="",
            )
            store.mark_applied(
                job, application_method="portal_verified_posthoc",
                note="LinkedIn application status verified manually",
            )
            # A zero-day cooldown, missing prior JD, or new location
            # must never permit an exact job to be submitted again.
            from dataclasses import replace
            updated = replace(
                job, location="Remote, India",
                description="A substantially different job description " * 50,
            )
            self.assertTrue(store.is_applied(updated))
            self.assertTrue(store.is_recent_similar_application(updated, cooldown_days=0))
            self.assertTrue(store.is_recent_similar_application(updated, cooldown_days=90))
            unrelated = replace(updated, external_id="4499999999",
                                url="https://www.linkedin.com/jobs/view/4499999999/")
            self.assertFalse(store.is_recent_similar_application(unrelated, cooldown_days=0))


if __name__ == "__main__":
    unittest.main()
