import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from naukri_ats_gate import audit_ats_form

URL = "https://www.naukri.com/job-listings-customer-support-manager-example-123"
ATS_ORIGIN = "https://jobs.examplecareers.com"


def qualified_report():
    return {
        "portal": "naukri", "mode": "READ_ONLY", "submitted": 0,
        "confirmed": 0, "threshold": 75,
        "jobs": [{
            "url": URL, "title": "Customer Support Manager", "company": "Example",
            "score": 90, "status": "QUALIFIED_FOR_REVIEW", "review_flags": [],
        }]
    }


def ats_inspection(**overrides):
    payload = {
        "schema_version": 1,
        "portal": "external_ats",
        "mode": "READ_ONLY_FORM_INSPECTION",
        "status": "read_only_inspection",
        "site_origin": ATS_ORIGIN,
        "source_naukri_job_url": URL,
        "handoff_method": "user_reported_external_apply",
        "handoff_navigation_verified": False,
        "fields": [
            {"type": "email", "category": "email", "required": True},
            {"type": "text", "category": "other_question", "required": True},
        ],
        "action_controls": ["submit_application"],
        "captcha_present": False, "otp_present": False, "login_required": False,
        "submitted": 0, "confirmed": 0,
    }
    payload.update(overrides)
    return payload


class NaukriATSGateTests(unittest.TestCase):
    def test_qualified_job_does_not_imply_verified_handoff_or_submission(self):
        result = audit_ats_form(qualified_report(), ats_inspection())
        self.assertTrue(result["qualified_job_matched"])
        self.assertFalse(result["handoff_navigation_verified"])
        self.assertEqual(result["status"], "ATS_FORM_OBSERVED_UNVERIFIED_HANDOFF")
        self.assertEqual(result["required_field_count"], 2)
        self.assertEqual(result["unclassified_question_count"], 1)
        self.assertTrue(result["submit_control_detected"])
        self.assertEqual(result["confirmed"], 0)
        self.assertEqual(result["submitted"], 0)

    def test_unrelated_ats_inspection_cannot_be_associated_with_candidate_job(self):
        result = audit_ats_form(
            qualified_report(),
            ats_inspection(source_naukri_job_url="https://www.naukri.com/job-listings-other-456"),
        )
        self.assertFalse(result["qualified_job_matched"])
        self.assertEqual(result["status"], "ATS_NOT_FOR_QUALIFIED_JOB")

    def test_security_challenge_keeps_application_blocked(self):
        result = audit_ats_form(qualified_report(), ats_inspection(otp_present=True))
        self.assertEqual(result["status"], "HUMAN_SECURITY_ACTION_REQUIRED")
        self.assertEqual(result["submitted"], 0)

    def test_fake_provenance_claim_fails(self):
        for variant in (
            {"handoff_method": "user_manually_opened_external_apply"},
            {"handoff_navigation_verified": True},
            {"handoff_navigation_verified": None},
            {"submitted": 1},
            {"confirmed": 1},
            {"site_origin": "https://accounts.google.com"},
            {"site_origin": "https://evil.com@jobs.examplecareers.com/path"},
        ):
            with self.subTest(variant=variant):
                with self.assertRaises(ValueError):
                    audit_ats_form(qualified_report(), ats_inspection(**variant))

    def test_unqualified_report_fails_closed(self):
        source = qualified_report()
        source["jobs"][0]["status"] = "MANUAL_REVIEW_REQUIRED"
        result = audit_ats_form(source, ats_inspection())
        self.assertFalse(result["qualified_job_matched"])


if __name__ == "__main__":
    unittest.main()
