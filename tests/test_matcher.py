import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matcher import score_job, score_profile
from models import CandidateProfile, Job


def profile() -> CandidateProfile:
    return CandidateProfile(
        target_roles=("customer success manager", "technical support manager"),
        skills=("customer success", "technical support", "sla", "incident management"),
        preferred_locations=("india", "remote"),
        remote_allowed=True,
        total_experience_years=8,
        india_authorized=True,
        outside_india_sponsorship_required=True,
        blocked_title_terms=("sales manager", "software engineer"),
        skill_taxonomy=("customer success", "technical support", "sla", "incident management", "sql"),
    )


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
        job = Job(
            "demo", "1", "A", "Customer Success Manager", "India", "u", "",
            required_skills=("customer success", "sla", "incident management"),
            minimum_years=5,
        )
        result = score_profile(profile(), job, 75)
        self.assertGreaterEqual(result.score, 75)
        self.assertEqual(result.decision, "APPLY")

    def test_irrelevant_title_is_role_gated(self):
        job = Job(
            "demo", "2", "A", "Finance Manager", "India", "u", "",
            required_skills=("sla", "incident management"),
            minimum_years=5,
        )
        result = score_profile(profile(), job, 75)
        self.assertEqual(result.decision, "SKIP")
        self.assertIn("role_gate<55", result.reasons)

    def test_blocked_title_is_skipped(self):
        job = Job(
            "demo", "3", "A", "Sales Manager", "India", "u", "",
            required_skills=("customer success", "sla", "incident management"),
            minimum_years=5,
        )
        result = score_profile(profile(), job, 75)
        self.assertEqual(result.decision, "SKIP")
        self.assertTrue(any(r.startswith("blocked_title=") for r in result.reasons))


if __name__ == "__main__":
    unittest.main()
