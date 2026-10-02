import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jd_enrichment import enrich_job_from_text
from models import Job


class JDEnrichmentTests(unittest.TestCase):
    def test_full_jd_recomputes_signals(self):
        job = Job(
            "indeed", "1", "A", "Customer Success Manager",
            "Remote", "https://example.invalid/1", "",
        )
        description = (
            "We are hiring a Customer Success Manager to own onboarding, SLA and "
            "stakeholder management for enterprise customers. This role requires "
            "minimum 6 years experience. We are remote worldwide and offer visa "
            "sponsorship and relocation assistance for eligible candidates."
        )
        result = enrich_job_from_text(
            job,
            description,
            ("customer success", "onboarding", "sla", "stakeholder management"),
        )
        self.assertTrue(result.enriched)
        self.assertEqual(result.job.minimum_years, 6)
        self.assertTrue(result.job.remote)
        self.assertIn("sla", result.job.required_skills)

    def test_short_jd_fails_closed(self):
        job = Job("indeed", "2", "A", "Role", "India", "u", "")
        result = enrich_job_from_text(job, "Very short description", ())
        self.assertFalse(result.enriched)
        self.assertEqual(result.reason, "jd_too_short_or_missing")


if __name__ == "__main__":
    unittest.main()
