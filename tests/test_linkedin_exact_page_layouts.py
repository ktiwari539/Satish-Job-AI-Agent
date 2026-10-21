"""Regression: exact-job detail view can use public layout and hydrate late."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from linkedin_exact_job import inspect_exact_linkedin_job, parse_linkedin_target

JOB_URL = "https://www.linkedin.com/jobs/view/4476701830/"
SKILLS = ("customer success", "sla", "stakeholder management", "onboarding")
LONG_JD = "Customer success SLA stakeholder management onboarding " * 9


class TextElement:
    def __init__(self, text="", visible=True):
        self.text = text
        self.visible = visible
    def is_visible(self):
        return self.visible
    def inner_text(self, timeout=0):
        return self.text


class Locator:
    def __init__(self, elements):
        self.elements = elements
    @property
    def first(self):
        return self.elements[0] if self.elements else TextElement(visible=False)
    def nth(self, index):
        return self.elements[index]
    def count(self):
        return len(self.elements)


class Page:
    def __init__(self, values, pending=None):
        self.url = JOB_URL
        self.values = values
        self.pending = pending
        self.waits = []
    def locator(self, key):
        return Locator(self.values.get(key, []))
    def wait_for_timeout(self, ms):
        self.waits.append(ms)
        if self.pending is not None:
            self.values = self.pending
            self.pending = None


def guest_layout():
    return {
        "h1.top-card-layout__title": [TextElement("Customer Success Manager")],
        ".topcard__org-name-link": [TextElement("Example Employer")],
        ".topcard__flavor--bullet": [TextElement("India")],
        ".show-more-less-html__markup": [TextElement(LONG_JD)],
    }


class ExactJobPublicLayoutTests(unittest.TestCase):
    def inspect(self, page):
        with patch("linkedin_exact_job.bounded_goto"):
            return inspect_exact_linkedin_job(
                page, parse_linkedin_target(JOB_URL), SKILLS
            )

    def test_standalone_public_layout_detects_all_metadata_without_wait(self):
        page = Page(guest_layout())
        with patch("linkedin_exact_job.trace_event") as trace:
            job = self.inspect(page)
        self.assertEqual(job.title, "Customer Success Manager")
        self.assertEqual(job.company, "Example Employer")
        self.assertEqual(job.location, "India")
        self.assertEqual(len(job.required_skills), 4)
        self.assertEqual(page.waits, [])
        self.assertEqual(trace.call_args.args[0], "exact_job_metadata_probe")
        self.assertEqual(trace.call_args.kwargs["missing_fields"], [])

    def test_hidden_first_result_does_not_block_visible_second(self):
        values = guest_layout()
        values["h1.top-card-layout__title"] = [
            TextElement("Unrelated hidden job", visible=False),
            TextElement("Customer Success Manager"),
        ]
        self.assertEqual(self.inspect(Page(values)).title, "Customer Success Manager")

    def test_deferred_public_details_render_after_short_wait(self):
        page = Page({}, pending=guest_layout())
        job = self.inspect(page)
        self.assertEqual(job.external_id, "4476701830")
        self.assertEqual(page.waits, [1100])

    def test_missing_title_and_company_is_diagnosed_without_submitting(self):
        values = guest_layout()
        del values["h1.top-card-layout__title"]
        del values[".topcard__org-name-link"]
        page = Page(values)
        with patch("linkedin_exact_job.trace_event") as trace:
            with self.assertRaisesRegex(ValueError, "exact_job_metadata_unverified:title,company"):
                self.inspect(page)
        self.assertEqual(page.waits, [1100])
        self.assertEqual(trace.call_args.kwargs["missing_fields"], ["title", "company"])
        self.assertNotIn(LONG_JD, str(trace.call_args.kwargs))

    def test_wrong_job_id_never_reads_or_uses_its_metadata(self):
        page = Page(guest_layout())
        page.url = "https://www.linkedin.com/jobs/view/4477371718/"
        with patch("linkedin_exact_job.bounded_goto"):
            with self.assertRaisesRegex(ValueError, "id_mismatch"):
                inspect_exact_linkedin_job(page, parse_linkedin_target(JOB_URL), SKILLS)


if __name__ == "__main__":
    unittest.main()
