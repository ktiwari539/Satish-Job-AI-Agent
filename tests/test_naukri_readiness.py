import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from naukri_readiness import clean_company_name, job_readiness_flags
from naukri_browser_import import evaluate_export
from models import CandidateProfile
from types import SimpleNamespace

PROFILE = CandidateProfile.from_dict({
    "target_roles": ["customer success manager", "customer support manager"],
    "skills": ["customer success", "customer support", "sla", "stakeholder management", "onboarding"],
    "skill_taxonomy": ["customer success", "customer support", "sla", "stakeholder management", "onboarding"],
    "preferred_locations": ["india"],
    "remote_allowed": True, "total_experience_years": 8,
    "india_authorized": True, "outside_india_sponsorship_required": True,
})
POLICY = SimpleNamespace(threshold=75, duplicate_cooldown_days=90)


class Store:
    def is_recent_similar_application(self, *args, **kwargs):
        return False


def export(job):
    return dict(schema_version=1, portal="naukri", page_kind="detail",
                jobs=[dict(job, capture_kind="detail")])


def job(*, title="Customer Success Manager", company="Madhus Garage Equipments\n3.092 Reviews",
        years="5-to-10", description=None):
    return dict(title=title, company=company, location="Bengaluru, India",
                url="https://www.naukri.com/job-listings-customer-success-manager-bengaluru-" + years + "-years-081026507157",
                description=description or (
                    "We are hiring a customer success manager to manage customer support "
                    "and onboarding. Track SLA and stakeholder management outcomes. " * 4
                ))


class NaukriReadinessTests(unittest.TestCase):
    def test_ratings_removed_from_employer_name(self):
        self.assertEqual(clean_company_name("Money View\n4.0340 Reviews"), "Money View")
        self.assertEqual(clean_company_name("Info Edge\n3.82.5K Reviews"), "Info Edge")
        self.assertEqual(clean_company_name("Sample Company"), "Sample Company")

    def test_correct_seniority_and_employer_can_still_qualify(self):
        result = evaluate_export(export(job()), PROFILE, POLICY, Store())
        self.assertEqual(result["qualified"], 1)
        self.assertEqual(result["jobs"][0]["company"], "Madhus Garage Equipments")
        self.assertEqual(result["jobs"][0]["status"], "QUALIFIED_FOR_REVIEW")

    def test_experience_range_conflict_holds_qualification_for_review(self):
        item = job(company="Money View", years="1-to-5")
        result = evaluate_export(export(item), PROFILE, POLICY, Store())
        self.assertEqual(result["qualified"], 0)
        self.assertEqual(result["jobs"][0]["status"], "MANUAL_REVIEW_REQUIRED")
        self.assertIn("experience_range_review_required", result["jobs"][0]["review_flags"])

    def test_restricted_title_never_assumes_candidate_eligibility(self):
        item = job(title="Customer Success Manager (Female only)", company="A Startup")
        result = evaluate_export(export(item), PROFILE, POLICY, Store())
        self.assertEqual(result["qualified"], 0)
        self.assertIn("restricted_eligibility_needs_human_review",
                      result["jobs"][0]["review_flags"])

    def test_generic_recruiter_identity_triggers_review(self):
        item = job(company="Call 7892301060 schedule your interview")
        result = evaluate_export(export(item), PROFILE, POLICY, Store())
        self.assertEqual(result["qualified"], 0)
        self.assertIn("unverified_employer_identity", result["jobs"][0]["review_flags"])

    def test_full_jd_teaser_does_not_count_as_full_description(self):
        item = job(description=(
            "This is a customer success and customer support role. " * 6 +
            "Click the Apply Now button to read the full job description for this role & start your application process!"
        ))
        result = evaluate_export(export(item), PROFILE, POLICY, Store())
        self.assertEqual(result["full_jd"], 0)
        self.assertEqual(result["needing_full_jd"], 1)
        self.assertEqual(result["qualified"], 0)

    def test_aggregated_posting_requires_verification_but_not_false_disqualification(self):
        item = job(description=job()["description"] +
                   " Disclaimer: This job posting has been aggregated from external source.")
        result = evaluate_export(export(item), PROFILE, POLICY, Store())
        self.assertIn("aggregated_posting_verify_availability",
                      result["jobs"][0]["warnings"])
        self.assertEqual(result["jobs"][0]["status"], "QUALIFIED_FOR_REVIEW")

    def test_experience_upper_bound_is_a_review_not_strict_rejection(self):
        hard, soft = job_readiness_flags("Support Manager", "Real Co",
                                         job(years="3-to-7")["url"],
                                         "Long detailed JD", 8)
        self.assertEqual(hard, ())
        self.assertEqual(soft, ())


if __name__ == "__main__":
    unittest.main()
