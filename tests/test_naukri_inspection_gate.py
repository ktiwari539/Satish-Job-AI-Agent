import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from naukri_inspection_gate import correlate_inspection


URL = "https://www.naukri.com/job-listings-customer-support-manager-example-5-to-10-years-123"
OTHER = "https://www.naukri.com/job-listings-customer-success-money-view-1-to-5-years-456"


def report(url=URL):
    return {
        "portal": "naukri", "mode": "READ_ONLY", "submitted": 0,
        "confirmed": 0, "threshold": 75,
        "jobs": [{
            "url": url, "title": "Customer Support Manager", "company": "Example",
            "score": 89, "status": "QUALIFIED_FOR_REVIEW", "review_flags": [],
        }],
    }


def inspection(url=URL, categories=None, **extra):
    return {
        "portal": "naukri", "schema_version": 2,
        "mode": "READ_ONLY_INSPECTION",
        "job_url": url,
        "application_controls": categories if categories is not None else ["apply"],
        **extra,
    }


class NaukriInspectionGateTests(unittest.TestCase):
    def test_native_apply_is_not_mistaken_for_submitted(self):
        result = correlate_inspection(report(), inspection())
        self.assertTrue(result["qualified_job_matched"])
        self.assertEqual(result["status"], "NAUKRI_APPLY_CONTROL_REVIEW_REQUIRED")
        self.assertEqual(result["submitted"], 0)
        self.assertEqual(result["confirmed"], 0)

    def test_external_apply_requires_followup_ats_inspection(self):
        result = correlate_inspection(report(), inspection(categories=["external_apply"]))
        self.assertEqual(result["status"], "EXTERNAL_APPLICATION_INSPECTION_REQUIRED")

    def test_unrelated_report_does_not_authorize_different_job(self):
        result = correlate_inspection(report(), inspection(url=OTHER))
        self.assertEqual(result["status"], "INSPECTION_NOT_FOR_QUALIFIED_JOB")
        self.assertFalse(result["qualified_job_matched"])

    def test_challenge_or_existing_application_is_fail_closed(self):
        blocked = correlate_inspection(
            report(), inspection(categories=["apply"], otp_present=True)
        )
        self.assertEqual(blocked["status"], "HUMAN_AUTHENTICATION_REQUIRED")
        applied = correlate_inspection(report(), inspection(categories=["already_applied"]))
        self.assertEqual(applied["status"], "POSSIBLY_ALREADY_APPLIED")

    def test_qualified_job_with_unresolved_flags_is_not_accepted(self):
        data = report()
        data["jobs"][0]["review_flags"] = ["experience_range_review_required"]
        with self.assertRaisesRegex(ValueError, "qualified_job_has_unresolved_review_flags"):
            correlate_inspection(data, inspection())

    def test_invalid_source_and_schema_rejected(self):
        for invalid in (
            inspection(url="https://evil.example/job"),
            inspection(schema_version=3),
            inspection(mode="LIVE"),
        ):
            with self.assertRaises(ValueError):
                correlate_inspection(report(), invalid)


if __name__ == "__main__":
    unittest.main()
