import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models import Job
from store import JobStore


class StoreTests(unittest.TestCase):
    def test_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            job = Job("demo", "1", "A", "Role", "India", "https://example.invalid", "")
            self.assertFalse(store.is_duplicate(job))
            store.mark_seen(job)
            self.assertTrue(store.is_duplicate(job))

    def test_cross_portal_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            first = Job(
                "linkedin", "1", "Example Pvt Ltd",
                "Customer Success Manager - Remote",
                "Mumbai, India", "https://linkedin.invalid/1", "",
            )
            second = Job(
                "indeed", "99", "Example",
                "Customer Success Manager",
                "Mumbai, India", "https://indeed.invalid/99", "",
            )
            store.mark_seen(first)
            self.assertTrue(store.is_duplicate(second))


if __name__ == "__main__":
    unittest.main()
