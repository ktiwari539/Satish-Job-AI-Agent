import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from browser_portals import (
    BrowserFormSnapshot,
    LinkedInBrowserAdapter,
    classify_linkedin_probe,
    classify_naukri_probe,
    inspect_form_snapshot,
    linkedin_search_url,
    naukri_search_url,
)


class FakeSearchPage:
    def __init__(self, url="", fail=True):
        self.url = url
        self.fail = fail
        self.goto_calls = []
        self.wait_calls = []

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append((url, wait_until, timeout))
        if not self.url:
            self.url = url
        if self.fail:
            raise RuntimeError("simulated navigation timeout")

    def wait_for_load_state(self, state, timeout=None):
        self.wait_calls.append((state, timeout))
        raise RuntimeError("simulated domcontentloaded timeout")

    def wait_for_timeout(self, timeout):
        self.wait_calls.append(("sleep", timeout))


class BrowserPortalTests(unittest.TestCase):
    def test_linkedin_search_tolerates_timeout_after_expected_route_loaded(self):
        page = FakeSearchPage(
            "https://www.linkedin.com/jobs/search/?keywords=Customer+Success+Manager&location=India"
        )
        adapter = LinkedInBrowserAdapter(page)
        result = adapter.open_search("Customer Success Manager", "India")
        self.assertIn("linkedin.com/jobs/search", result)
        self.assertEqual(page.goto_calls[0][1], "commit")
        self.assertEqual(page.goto_calls[0][2], 15000)

    def test_linkedin_search_timeout_on_unexpected_route_fails_closed(self):
        page = FakeSearchPage("https://www.linkedin.com/checkpoint/challenge/123")
        adapter = LinkedInBrowserAdapter(page)
        with self.assertRaises(RuntimeError):
            adapter.open_search("Customer Success Manager", "India")

    def test_linkedin_search_url(self):
        url = linkedin_search_url("Technical Account Manager", "India")
        self.assertTrue(url.startswith("https://www.linkedin.com/jobs/search/?"))
        self.assertIn("Technical+Account+Manager", url)
        self.assertIn("location=India", url)

    def test_naukri_search_url_uses_jobseeker_route(self):
        self.assertEqual(
            naukri_search_url("Customer Success Manager", "Bengaluru"),
            "https://www.naukri.com/customer-success-manager-jobs-in-bengaluru",
        )

    def test_linkedin_probe_requires_authenticated_markers(self):
        self.assertTrue(
            classify_linkedin_probe(
                "https://www.linkedin.com/feed/",
                "Jobs My Network Messaging Notifications",
            ).authenticated
        )
        self.assertTrue(
            classify_linkedin_probe(
                "https://www.linkedin.com/jobs/",
                "Jobs My Network Messaging Notifications",
            ).authenticated
        )
        self.assertEqual(
            classify_linkedin_probe("https://www.linkedin.com/login").reason,
            "linkedin_login_required",
        )
        checkpoint = classify_linkedin_probe(
            "https://www.linkedin.com/checkpoint/challenge/123"
        )
        self.assertTrue(checkpoint.needs_human_action)

    def test_naukri_probe_fails_closed(self):
        logged_in = classify_naukri_probe(
            "https://www.naukri.com/",
            "Jobs Profile Performance View Profile Logout",
        )
        self.assertTrue(logged_in.authenticated)

        unknown = classify_naukri_probe("https://www.naukri.com/", "Search jobs")
        self.assertFalse(unknown.authenticated)
        self.assertEqual(unknown.reason, "naukri_session_not_confirmed")

    def test_form_inspector_blocks_captcha_and_unknown_required_fields(self):
        inspection = inspect_form_snapshot(
            BrowserFormSnapshot(
                body_text="Please verify you are human",
                required_field_names=("Full Name", "Desired Compensation"),
                captcha_selector_found=True,
            )
        )
        self.assertTrue(inspection.captcha_present)
        self.assertIn("Desired Compensation", inspection.required_unknown_fields)
        self.assertFalse(inspection.supported)

    def test_form_inspector_allows_known_fields(self):
        inspection = inspect_form_snapshot(
            BrowserFormSnapshot(
                body_text="Apply now",
                required_field_names=("Full Name", "Email", "Mobile Number", "Resume"),
            )
        )
        self.assertTrue(inspection.supported)
        self.assertEqual(inspection.required_unknown_fields, ())


if __name__ == "__main__":
    unittest.main()
