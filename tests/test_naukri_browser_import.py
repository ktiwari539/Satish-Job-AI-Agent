import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from models import CandidateProfile
from naukri_browser_import import (
    evaluate_export, parse_export, valid_naukri_url,
)


PROFILE = CandidateProfile.from_dict({
    "target_roles": ["customer success manager"],
    "skills": ["customer success", "sla", "stakeholder management", "onboarding"],
    "skill_taxonomy": ["customer success", "sla", "stakeholder management", "onboarding"],
    "preferred_locations": ["india"],
    "remote_allowed": True,
    "total_experience_years": 8,
    "india_authorized": True,
    "outside_india_sponsorship_required": True,
})
POLICY = SimpleNamespace(threshold=75, duplicate_cooldown_days=90)


class Store:
    def __init__(self, duplicate=False):
        self.duplicate = duplicate
        self.queries = []

    def is_recent_similar_application(self, job, cooldown_days=90):
        self.queries.append((job, cooldown_days))
        return self.duplicate


def payload(*, kind="detail", description=None, url="https://www.naukri.com/job-listings-sample-123", company="Example Co"):
    description = description if description is not None else (
        "We are hiring a Customer Success Manager based in Bengaluru, India. "
        "Manage customer success programs, SLA performance, stakeholder management "
        "and onboarding for business customers. " * 3
    )
    return {
        "schema_version": 1,
        "portal": "naukri",
        "page_kind": kind,
        "jobs": [{
            "title": "Customer Success Manager", "company": company,
            "location": "Bengaluru, India", "url": url,
            "description": description, "capture_kind": kind,
        }],
    }


class NaukriBrowserImportTests(unittest.TestCase):
    def test_import_scores_full_description_but_never_submits(self):
        result = evaluate_export(payload(), PROFILE, POLICY, Store())
        self.assertEqual(result["full_jd"], 1)
        self.assertEqual(result["qualified"], 1)
        self.assertEqual(result["jobs"][0]["status"], "QUALIFIED_FOR_REVIEW")
        self.assertGreaterEqual(result["jobs"][0]["score"], 75)
        self.assertEqual(result["submitted"], 0)
        self.assertEqual(result["confirmed"], 0)

    def test_search_card_never_passes_as_complete_jd(self):
        data = payload(kind="search")
        # Even a populated description from an untrusted export is not enough.
        result = evaluate_export(data, PROFILE, POLICY, Store())
        self.assertEqual(result["full_jd"], 0)
        self.assertEqual(result["qualified"], 0)
        self.assertEqual(result["needing_full_jd"], 1)

    def test_short_detail_is_not_scored(self):
        result = evaluate_export(payload(description="Apply here"), PROFILE, POLICY, Store())
        self.assertEqual(result["jobs"][0]["status"], "NEEDS_FULL_JD")

    def test_missing_company_is_not_qualified(self):
        result = evaluate_export(payload(company=""), PROFILE, POLICY, Store())
        self.assertEqual(result["qualified"], 0)
        self.assertEqual(result["needing_full_jd"], 1)

    def test_repeat_application_is_not_qualified(self):
        store = Store(duplicate=True)
        result = evaluate_export(payload(), PROFILE, POLICY, store)
        self.assertEqual(result["qualified"], 0)
        self.assertEqual(result["jobs"][0]["status"], "SKIPPED_RECENT_APPLICATION")
        self.assertEqual(store.queries[0][1], 90)

    def test_rejects_cross_domain_and_insecure_urls(self):
        for url in (
            "https://evil.com/job", "https://fakenaukri.com/jobs",
            "http://www.naukri.com/job", "https://www.naukri.com@evil.com/jobs",
            "https://www.naukri.com:444/jobs", "https://www.naukri.com/",
        ):
            self.assertFalse(valid_naukri_url(url), url)
            with self.assertRaises(ValueError):
                parse_export(payload(url=url), PROFILE.skill_taxonomy)

    def test_accepts_proper_naukri_job_url(self):
        self.assertTrue(valid_naukri_url("https://www.naukri.com/job-listings-example-123"))

    def test_rejects_malformed_and_inconsistent_export(self):
        cases = [
            {"schema_version": 1, "portal": "not-naukri", "jobs": []},
            {"schema_version": 1, "portal": "naukri", "page_kind": "search", "jobs": [{}]},
            dict(payload(), jobs=[dict(payload()["jobs"][0], capture_kind="search")]),
            dict(payload(), jobs="not a list"),
        ]
        for case in cases:
            with self.assertRaises(ValueError):
                parse_export(case, PROFILE.skill_taxonomy)

    def test_duplicate_urls_scored_once(self):
        first = payload()
        first["jobs"].append(dict(first["jobs"][0]))
        result = evaluate_export(first, PROFILE, POLICY, Store())
        self.assertEqual(result["discovered"], 1)


if __name__ == "__main__":
    unittest.main()
