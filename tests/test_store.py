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
            self.assertFalse(store.is_seen(job))
            store.mark_seen(job)
            self.assertTrue(store.is_seen(job))


if __name__ == "__main__":
    unittest.main()
