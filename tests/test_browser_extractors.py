import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from browser_extractors import (
    RawJobCard,
    canonicalize_job_url,
    normalize_browser_card,
    normalize_browser_cards,
    stable_external_id,
)


class BrowserExtractorTests(unittest.TestCase):
    def test_tracking_query_is_removed(self):
        self.assertEqual(
            canonicalize_job_url("https://example.com/jobs/123?trk=abc#top"),
            "https://example.com/jobs/123",
        )

    def test_explicit_external_id_is_preserved(self):
        card = RawJobCard("Role", "Company", "India", "https://example.com/j/1", "abc123")
        self.assertEqual(stable_external_id("linkedin", card), "abc123")

    def test_fallback_id_is_stable(self):
        card = RawJobCard("Role", "Company", "India", "https://example.com/j/1?x=1")
        self.assertEqual(
            stable_external_id("linkedin", card),
            stable_external_id("linkedin", card),
        )

    def test_normalization_extracts_job_signals(self):
        card = RawJobCard(
            "Customer Success Manager",
            "Example",
            "Remote - India",
            "https://example.com/jobs/1?tracking=abc",
            description="Own customer success and SLA. Minimum 5 years experience.",
        )
        job = normalize_browser_card(
            "linkedin",
            card,
            ("customer success", "sla", "jira"),
        )
        self.assertEqual(job.source, "linkedin")
        self.assertEqual(job.url, "https://example.com/jobs/1")
        self.assertIn("customer success", job.required_skills)
        self.assertIn("sla", job.required_skills)
        self.assertEqual(job.minimum_years, 5)
        self.assertTrue(job.remote)

    def test_invalid_and_duplicate_cards_are_filtered(self):
        cards = [
            RawJobCard("Role", "A", "India", "https://example.com/jobs/1", "1"),
            RawJobCard("Role", "A", "India", "https://example.com/jobs/1?trk=x", "1"),
            RawJobCard("", "A", "India", "https://example.com/jobs/2", "2"),
        ]
        jobs = normalize_browser_cards("naukri", cards, ())
        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()
