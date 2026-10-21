import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from linkedin_exact_job import parse_linkedin_target, inspect_exact_linkedin_job

SELECTED = "https://www.linkedin.com/jobs/search-results/?currentJobId=4476701830&originToLandingJobPostings=4476701830%2C4477371718"
DIRECT = "https://www.linkedin.com/jobs/view/4476701830/"


class Locator:
    def __init__(self, text):
        self.text = text
    @property
    def first(self):
        return self
    def count(self):
        return bool(self.text)
    def is_visible(self):
        return bool(self.text)
    def inner_text(self, timeout=0):
        return self.text


class Page:
    def __init__(self, url=DIRECT):
        self.url = url
        self.values = {
            ".job-details-jobs-unified-top-card__job-title h1": "Customer Success Manager",
            ".job-details-jobs-unified-top-card__company-name a": "Example Employer",
            ".job-details-jobs-unified-top-card__primary-description-container": "India",
            ".jobs-description__content": (
                "Required: customer success, stakeholder management, SLA, onboarding. " * 7
            ),
        }
    def locator(self, key):
        return Locator(self.values.get(key, ""))


class ExactJobTests(unittest.TestCase):
    def test_selected_search_result_is_one_canonical_job(self):
        target = parse_linkedin_target(SELECTED)
        self.assertEqual(target.job_id, "4476701830")
        self.assertEqual(target.url, DIRECT)

    def test_direct_job_is_supported(self):
        self.assertEqual(parse_linkedin_target(DIRECT + "?tracking=anything").url, DIRECT)

    def test_ambiguous_or_foreign_urls_rejected(self):
        urls = (
            "https://www.linkedin.com.evil.test/jobs/view/4476701830/",
            "http://www.linkedin.com/jobs/view/4476701830/",
            "https://www.linkedin.com/jobs/search-results/",
            "https://www.linkedin.com/jobs/search-results/?currentJobId=4476701830&currentJobId=4477371718",
            "https://www.linkedin.com/jobs/search-results/?currentJobId=1",
            "https://www.linkedin.com/feed/",
        )
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_linkedin_target(url)

    def test_metadata_required_from_exact_page(self):
        page = Page()
        with patch("linkedin_exact_job.bounded_goto"):
            job = inspect_exact_linkedin_job(
                page, parse_linkedin_target(SELECTED),
                ("customer success", "stakeholder management", "sla", "onboarding"),
            )
        self.assertEqual(job.external_id, "4476701830")
        self.assertEqual(job.title, "Customer Success Manager")
        self.assertEqual(len(job.required_skills), 4)

    def test_wrong_job_redirect_and_missing_description_rejected(self):
        page = Page("https://www.linkedin.com/jobs/view/4477371718/")
        with patch("linkedin_exact_job.bounded_goto"), self.assertRaises(ValueError):
            inspect_exact_linkedin_job(page, parse_linkedin_target(SELECTED), ())
        page = Page()
        page.values[".jobs-description__content"] = ""
        with patch("linkedin_exact_job.bounded_goto"), self.assertRaises(ValueError):
            inspect_exact_linkedin_job(page, parse_linkedin_target(SELECTED), ())


if __name__ == "__main__":
    unittest.main()
