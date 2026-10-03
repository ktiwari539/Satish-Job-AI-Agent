import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models import Job
from store import JobStore


class AppliedUrlTests(unittest.TestCase):
    def test_applied_url_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            job = Job(
                source="linkedin",
                external_id="4470567267",
                company="Hexaware Technologies",
                title="Assistant Manager",
                location="",
                url="https://www.linkedin.com/jobs/view/4470567267/",
                description="",
            )
            store.mark_applied(job, application_method="manual")
            self.assertTrue(store.is_applied_url(job.url))
            self.assertFalse(
                store.is_applied_url("https://www.linkedin.com/jobs/view/9999999999/")
            )


if __name__ == "__main__":
    unittest.main()
