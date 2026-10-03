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


if __name__ == "__main__":
    unittest.main()
