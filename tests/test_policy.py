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

    def test_outside_india_onsite_is_blocked(self):
        job = Job("demo", "2", "A", "Customer Success Manager", "New York, United States", "u", "")
        result = evaluate_eligibility(PROFILE, job)
        self.assertFalse(result.eligible)
        self.assertIn("outside_preferred_location", result.reasons)

    def test_outside_india_no_sponsorship_is_blocked(self):
        job = Job(
            "demo", "3", "A", "Customer Success Manager",
            "Remote - United States", "u", "We will not sponsor visas.", remote=True
        )
        result = evaluate_eligibility(PROFILE, job)
        self.assertFalse(result.eligible)
        self.assertIn("outside_india_requires_sponsorship_but_job_does_not_offer_it", result.reasons)

    def test_outside_india_remote_requires_explicit_sponsorship(self):
        job = Job(
            "demo", "4", "A", "Technical Account Manager",
            "USA, Remote", "u", "Remote role for US customers.", remote=True
        )
        result = evaluate_eligibility(PROFILE, job)
        self.assertFalse(result.eligible)
        self.assertIn("outside_india_remote_requires_explicit_sponsorship", result.reasons)

    def test_outside_india_remote_with_sponsorship_can_pass(self):
        job = Job(
            "demo", "5", "A", "Technical Account Manager",
            "Remote - Europe", "u", "Visa sponsorship available for the right candidate.", remote=True
        )
        result = evaluate_eligibility(PROFILE, job)
        self.assertTrue(result.eligible)

    def test_large_experience_gap_is_blocked(self):
        job = Job(
            "demo", "6", "A", "Customer Success Manager",
            "India", "u", "", minimum_years=12
        )
        result = evaluate_eligibility(PROFILE, job)
        self.assertFalse(result.eligible)
        self.assertIn("experience_shortfall_over_2_years", result.reasons)


if __name__ == "__main__":
    unittest.main()
