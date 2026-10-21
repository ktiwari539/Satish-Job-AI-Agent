"""Read-only extraction from exact structured job data and blank page diagnostics."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from linkedin_exact_job import (
    inspect_exact_linkedin_job, parse_linkedin_target, _safe_page_state,
)

URL = "https://www.linkedin.com/jobs/view/4476701830/"
TAXONOMY = ("customer success", "sla", "onboarding", "stakeholder management")
DESCRIPTION = "Customer success SLA stakeholder management onboarding " * 9


class Script:
    def __init__(self, content):
        self.content = content
    def text_content(self, timeout=0):
        return self.content


class ScriptList:
    def __init__(self, items):
        self.items = items
    def count(self):
        return len(self.items)
    def nth(self, index):
        return Script(self.items[index])


class EmptyLocator:
    @property
    def first(self):
        return self
    def count(self):
        return 0
    def is_visible(self):
        return False


class Page:
    def __init__(self, structured=(), *, signals=None):
        self.url = URL
        self.scripts = [json.dumps(x) for x in structured]
        self.signals = signals
        self.wait_calls = 0
    def locator(self, selector):
        if selector == 'script[type="application/ld+json"]':
            return ScriptList(self.scripts)
        return EmptyLocator()
    def wait_for_timeout(self, milliseconds):
        self.wait_calls += 1
    def evaluate(self, script):
        if self.signals is None:
            raise RuntimeError("JS disabled in test")
        return self.signals


def sample_posting(job_id="4476701830", url=True, identifier=False):
    obj = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Customer Success Manager",
        "description": DESCRIPTION,
        "hiringOrganization": {"name": "Example Employer"},
        "jobLocation": {
            "address": {
                "addressLocality": "Bengaluru",
                "addressRegion": "Karnataka",
                "addressCountry": "IN",
            }
        },
    }
    if url:
        obj["url"] = "https://www.linkedin.com/jobs/view/example-role-" + job_id
    if identifier:
        obj["identifier"] = {"@type": "PropertyValue", "value": job_id}
    return obj


class ReadOnlyFallbackTests(unittest.TestCase):
    def run_inspection(self, page):
        with patch("linkedin_exact_job.bounded_goto"):
            return inspect_exact_linkedin_job(page, parse_linkedin_target(URL), TAXONOMY)

    def test_structured_data_requires_matching_exact_job_id(self):
        page = Page(structured=[sample_posting()])
        with patch("linkedin_exact_job.trace_event") as trace:
            job = self.run_inspection(page)
        self.assertEqual(job.external_id, "4476701830")
        self.assertEqual(job.company, "Example Employer")
        self.assertIn("Bengaluru", job.location)
        self.assertEqual(len(job.required_skills), 4)
        events = [call.args[0] for call in trace.call_args_list]
        self.assertIn("exact_job_structured_data_used", events)

    def test_other_job_data_never_accepted(self):
        page = Page(structured=[sample_posting(job_id="4477371718")])
        with self.assertRaisesRegex(ValueError, "exact_job_metadata_unverified"):
            self.run_inspection(page)

    def test_unverified_jsonld_job_without_id_never_accepted(self):
        page = Page(structured=[sample_posting(url=False)])
        with self.assertRaisesRegex(ValueError, "exact_job_metadata_unverified"):
            self.run_inspection(page)

    def test_bound_identifier_is_accepted(self):
        page = Page(structured=[sample_posting(url=False, identifier=True)])
        self.assertEqual(self.run_inspection(page).external_id, "4476701830")

    def test_blank_page_classified_with_sanitized_state(self):
        signals = {
            "body_chars": 0, "main_count": 0, "detail_nodes": 0,
            "heading_count": 0, "job_posting_scripts": 0,
            "login_form_present": False, "challenge_present": False,
            "expired_text_present": False,
        }
        page = Page(signals=signals)
        self.assertEqual(_safe_page_state(page)["page_state"], "empty_or_unrendered_page")
        with patch("linkedin_exact_job.trace_event") as trace:
            with self.assertRaisesRegex(ValueError, "empty_or_unrendered_page"):
                self.run_inspection(page)
        result = trace.call_args.kwargs
        self.assertEqual(result["page_probe"]["job_posting_scripts"], 0)
        self.assertEqual(result["missing_fields"], ["title", "company", "location"])
        self.assertNotIn("text", str(result))

    def test_login_interstitial_classified_without_outputting_form(self):
        page = Page(signals={
            "body_chars": 600, "main_count": 0, "detail_nodes": 0,
            "heading_count": 1, "job_posting_scripts": 0,
            "login_form_present": True, "challenge_present": False,
            "expired_text_present": False,
        })
        with self.assertRaisesRegex(ValueError, "sign_in_interstitial"):
            self.run_inspection(page)

    def test_security_checkpoint_classification_takes_priority(self):
        page = Page(signals={
            "body_chars": 400, "main_count": 1, "detail_nodes": 0,
            "heading_count": 1, "job_posting_scripts": 0,
            "login_form_present": True, "challenge_present": True,
            "expired_text_present": False,
        })
        with self.assertRaisesRegex(ValueError, "security_checkpoint"):
            self.run_inspection(page)

    def test_different_domain_in_jsonld_is_not_trusted(self):
        sample = sample_posting()
        sample["url"] = "https://example.invalid/jobs/view/4476701830"
        with self.assertRaisesRegex(ValueError, "exact_job_metadata_unverified"):
            self.run_inspection(Page(structured=[sample]))


if __name__ == "__main__":
    unittest.main()
