"""Exact LinkedIn public-JD fallback: no credential reads and strict same-ID gates."""
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from linkedin_public_metadata import (
    exact_public_job_url, fetch_public_exact_linkedin_job,
    parse_public_job_html,
)

JOB_ID = "4461542106"
URL = "https://in.linkedin.com/jobs/view/sr-customer-success-manager-at-firework-4461542106"
JD = (
    "We seek an experienced customer success professional with 7+ years of "
    "account management in B2B SaaS. Own customer success strategy, "
    "onboarding, stakeholder management, renewals, retention and churn. "
    "Run QBR reviews, coordinate with Salesforce users and enterprise clients. "
    "Experience supporting customers in US business hours is important. "
    "The candidate will lead a portfolio and strengthen strategic relationships."
)
PAGE = (
    '<!doctype html><html><head><meta charset="utf-8"></head>'
    '<body><input type="hidden" value="noise">'
    '<h1 class="top-card-layout__title">Sr. Customer Success Manager</h1>'
    '<a class="topcard__org-name-link">Firework</a>'
    '<span class="topcard__flavor topcard__flavor--bullet">India</span>'
    '<div class="show-more-less-html__markup">'
    '<p>Role description</p><ul><li>' + JD + '</li></ul></div>'
    '</body></html>'
)


class FakeResponse:
    def __init__(self, url, body):
        self.url = url
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def geturl(self):
        return self.url
    def read(self, n):
        return self.body[:n]


class PublicMetadataTests(unittest.TestCase):
    def test_same_id_public_listing_parses_complete_jd_and_skills(self):
        job = parse_public_job_html(
            PAGE, JOB_ID, ("customer success", "stakeholder management",
                           "retention", "churn", "qbr", "salesforce", "b2b"),
        )
        self.assertEqual(job.title, "Sr. Customer Success Manager")
        self.assertEqual(job.company, "Firework")
        self.assertEqual(job.location, "India")
        self.assertEqual(job.external_id, JOB_ID)
        self.assertEqual(job.url, "https://www.linkedin.com/jobs/view/" + JOB_ID + "/")
        self.assertGreaterEqual(len(job.required_skills), 3)
        self.assertEqual(job.minimum_years, 7)

    def test_same_id_public_url_is_strict_and_strips_query(self):
        self.assertEqual(exact_public_job_url(URL + "?tracking=redacted", JOB_ID), URL)
        for value in (
            "https://evil.invalid/jobs/view/firework-" + JOB_ID,
            "http://in.linkedin.com/jobs/view/firework-" + JOB_ID,
            "https://in.linkedin.com/jobs/view/firework-4476701830",
            "https://in.linkedin.com.evil.invalid/jobs/view/firework-" + JOB_ID,
            "https://in.linkedin.com/jobs/search/?currentJobId=" + JOB_ID,
            "https://in.linkedin.com/jobs/view/firework-" + JOB_ID + "#section",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                exact_public_job_url(value, JOB_ID)

    def test_exact_id_redirect_required_and_no_cookies_sent(self):
        target = SimpleNamespace(
            job_id=JOB_ID, url="https://www.linkedin.com/jobs/view/" + JOB_ID + "/"
        )
        calls = []
        def fetch(request, timeout):
            calls.append((request, timeout))
            return FakeResponse(URL, PAGE.encode("utf-8"))
        with patch("linkedin_public_metadata.urlopen", side_effect=fetch):
            job = fetch_public_exact_linkedin_job(
                URL, target, ("customer success", "retention", "onboarding")
            )
        self.assertEqual(job.external_id, JOB_ID)
        self.assertEqual(calls[0][0].get_full_url(), URL)
        self.assertNotIn("Cookie", calls[0][0].headers)
        self.assertEqual(calls[0][1], 12)

        with patch(
            "linkedin_public_metadata.urlopen",
            return_value=FakeResponse(
                "https://in.linkedin.com/jobs/view/other-job-4476701830",
                PAGE.encode("utf-8"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "public_job_id_mismatch"):
                fetch_public_exact_linkedin_job(URL, target, ())

    def test_missing_details_and_oversized_response_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "metadata_incomplete"):
            parse_public_job_html("<title>Firework</title>", JOB_ID, ())
        target = SimpleNamespace(
            job_id=JOB_ID, url="https://www.linkedin.com/jobs/view/" + JOB_ID + "/"
        )
        with patch("linkedin_public_metadata.urlopen", return_value=FakeResponse(
            URL, b"x" * 2_000_001
        )):
            with self.assertRaisesRegex(ValueError, "oversize"):
                fetch_public_exact_linkedin_job(URL, target, ())

    def test_malformed_public_html_does_not_authorize_applying(self):
        target = SimpleNamespace(
            job_id=JOB_ID, url="https://www.linkedin.com/jobs/view/" + JOB_ID + "/"
        )
        with patch("linkedin_public_metadata.urlopen", return_value=FakeResponse(
            URL, b"<html>login</html>"
        )):
            with self.assertRaisesRegex(ValueError, "metadata_incomplete"):
                fetch_public_exact_linkedin_job(URL, target, ())


if __name__ == "__main__":
    unittest.main()
