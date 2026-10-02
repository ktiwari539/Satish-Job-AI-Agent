import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matcher import score_job, score_profile
from models import CandidateProfile, Job


class MatcherTests(unittest.TestCase):
    def test_strong_match_applies(self):
        result = score_job(
            ["customer success", "sla", "incident management", "stakeholder management"],
            ["customer success", "sla", "incident management", "stakeholder management"],
            threshold=75,
        )
        self.assertEqual(result.score, 100)
        self.assertEqual(result.decision, "APPLY")

    def test_partial_match_skips(self):
        result = score_job(
            ["customer success", "sla"],
            ["customer success", "sla", "salesforce", "sql"],
            threshold=75,
        )
        self.assertEqual(result.score, 50)
        self.assertEqual(result.decision, "SKIP")

    def test_empty_requirements_are_safe(self):
        result = score_job(["customer success"], [], threshold=75)
        self.assertEqual(result.score, 0)
        self.assertEqual(result.decision, "SKIP")

    def test_profile_weighted_match(self):
        profile = CandidateProfile(
            target_roles=("customer success manager",),
            skills=("customer success", "sla", "incident management", "stakeholder management"),
            preferred_locations=("india",),
            remote_allowed=True,
            total_experience_years=8,
            india_authorized=True,
            outside_india_sponsorship_required=True,
        )
        job = Job(
            "demo", "1", "A", "Customer Success Manager", "India", "u", "",
            required_skills=("customer success", "sla", "incident management", "stakeholder management"),
            minimum_years=5,
        )
        result = score_profile(profile, job, 75)
        self.assertEqual(result.score, 100)
        self.assertEqual(result.decision, "APPLY")


if __name__ == "__main__":
    unittest.main()
