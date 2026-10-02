import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from international import classify_search_track, detect_international_signals
from models import Job


class InternationalTests(unittest.TestCase):
    def test_relocation_signal(self):
        job = Job(
            "demo", "1", "A", "Customer Success Manager",
            "Berlin, Germany", "u",
            "Relocation assistance and visa sponsorship available.",
        )
        signals = detect_international_signals(job)
        self.assertTrue(signals.sponsorship_positive)
        self.assertTrue(signals.relocation_positive)
        self.assertEqual(classify_search_track(job), "global_relocation")

    def test_global_remote_signal(self):
        job = Job(
            "demo", "2", "A", "Technical Account Manager",
            "Remote", "u",
            "Remote worldwide. Work from anywhere.",
            remote=True,
        )
        self.assertEqual(classify_search_track(job), "global_remote")

    def test_unverified_international(self):
        job = Job(
            "demo", "3", "A", "Support Manager",
            "London, UK", "u",
            "Office-based position.",
        )
        self.assertEqual(classify_search_track(job), "international_unverified")


if __name__ == "__main__":
    unittest.main()
