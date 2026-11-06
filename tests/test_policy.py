import unittest
from pathlib import Path
import sys
from dataclasses import replace

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

    def test_unverified_overseas_role_is_blocked(self):
        job = Job("demo", "2", "A", "Customer Success Manager", "New York, United States", "u", "")
        result = evaluate_eligibility(PROFILE, job)
        self.assertFalse(result.eligible)
        self.assertIn(
            "outside_india_requires_explicit_sponsorship_or_global_remote_signal",
            result.reasons,
        )

    def test_outside_india_no_sponsorship_is_blocked(self):
        job = Job(
            "demo", "3", "A", "Customer Success Manager",
            "Remote - United States", "u", "We will not sponsor visas.", remote=True
        )
        result = evaluate_eligibility(PROFILE, job)
        self.assertFalse(result.eligible)
        self.assertIn("outside_india_requires_sponsorship_but_job_does_not_offer_it", result.reasons)

    def test_outside_india_with_sponsorship_can_pass(self):
        job = Job(
            "demo", "4", "A", "Technical Account Manager",
            "Amsterdam, Netherlands", "u",
            "Visa sponsorship available for the right candidate.",
        )
        result = evaluate_eligibility(PROFILE, job)
        self.assertTrue(result.eligible)

    def test_global_remote_can_pass(self):
        job = Job(
            "demo", "5", "A", "Technical Account Manager",
            "Remote", "u",
            "Remote worldwide. Work from anywhere.",
            remote=True,
        )
        result = evaluate_eligibility(PROFILE, job)
        self.assertTrue(result.eligible)

    def test_missing_location_is_review_required_not_assumed_overseas(self):
        for location in ('','Remote','Hybrid','Not specified'):
            job=Job('fixture','missing','A','Customer Success Manager',location,'u','',remote=location=='Remote')
            self.assertEqual(evaluate_eligibility(PROFILE,job).reasons,('job_work_location_unverified',))

    def test_indiana_is_not_india(self):
        job=Job('fixture','indiana','A','Customer Success Manager','Indianapolis, Indiana, United States','u','')
        self.assertFalse(evaluate_eligibility(PROFILE,job).eligible)

    def test_relocation_costs_do_not_establish_visa_sponsorship(self):
        job=Job('fixture','relocation','A','Customer Success Manager','London, UK','u','Relocation assistance available.')
        self.assertFalse(evaluate_eligibility(PROFILE,job).eligible)

    def test_generic_remote_does_not_establish_worldwide_eligibility(self):
        job=Job('fixture','remote','A','Customer Success Manager','New York, United States','u','Work remotely.',remote=True)
        self.assertFalse(evaluate_eligibility(PROFILE,job).eligible)

    def test_global_remote_requires_remote_permission_and_verified_india_fact(self):
        job=Job('fixture','global','A','Customer Success Manager','Remote','u','Remote worldwide.',remote=True)
        for profile in (replace(PROFILE,india_authorized=False),replace(PROFILE,remote_allowed=False)):
            self.assertFalse(evaluate_eligibility(profile,job).eligible)

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
