import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models import CandidateProfile, Job
from policy import evaluate_eligibility


PROFILE = CandidateProfile(
    target_roles=("customer success manager",),
    skills=("customer success",),
    preferred_locations=("india", "remote"),
    remote_allowed=True,
    total_experience_years=8,
    india_authorized=True,
    outside_india_sponsorship_required=True,
)


class PolicyTests(unittest.TestCase):
    def test_india_role_is_eligible(self):
        job = Job("demo", "1", "A", "Customer Success Manager", "Mumbai, India", "u", "")
        self.assertTrue(evaluate_eligibility(PROFILE, job).eligible)

    def test_outside_india_no_sponsorship_is_blocked(self):
        job = Job("demo", "2", "A", "Customer Success Manager", "New York, United States", "u", "We will not sponsor visas.")
        result = evaluate_eligibility(PROFILE, job)
        self.assertFalse(result.eligible)
        self.assertIn("outside_india_requires_sponsorship_but_job_does_not_offer_it", result.reasons)


if __name__ == "__main__":
    unittest.main()
