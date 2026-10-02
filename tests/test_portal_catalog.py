import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from portal_catalog import PORTAL_TARGETS, build_search_url


class PortalCatalogTests(unittest.TestCase):
    def test_major_portals_are_registered(self):
        expected = {
            "linkedin", "naukri", "indeed", "foundit", "instahyre",
            "cutshort", "wellfound", "hirist", "glassdoor",
            "greenhouse", "lever", "workday",
        }
        self.assertTrue(expected.issubset(PORTAL_TARGETS))

    def test_indeed_search_url(self):
        url = build_search_url("indeed", "Customer Success Manager", "India")
        self.assertIn("q=Customer+Success+Manager", url)
        self.assertIn("l=India", url)

    def test_browser_form_portal_returns_safe_start_url(self):
        self.assertEqual(
            build_search_url("wellfound", "Customer Success Manager", "Remote"),
            "https://wellfound.com/jobs",
        )


if __name__ == "__main__":
    unittest.main()
