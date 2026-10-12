import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import job_agent_cli
from browser_portals import NaukriBrowserAdapter, classify_naukri_probe


class MultiPortalDispatchTests(unittest.TestCase):
    def test_naukri_can_be_selected_without_linkedin(self):
        with patch.object(sys, "argv", ["job_agent_cli.py", "--portal", "naukri", "--max-jobs", "3"]):
            args = job_agent_cli.parse_args()
        self.assertEqual(args.portal, "naukri")
        self.assertEqual(args.max_jobs, 3)

    def test_default_remains_linkedin(self):
        with patch.object(sys, "argv", ["job_agent_cli.py"]):
            self.assertEqual(job_agent_cli.parse_args().portal, "linkedin")

    def test_naukri_classifies_login_challenge_as_unverified(self):
        result = classify_naukri_probe(
            "https://www.naukri.com/nlogin/login",
            "Enter your credentials",
        )
        self.assertFalse(result.authenticated)

    def test_naukri_has_independent_adapter(self):
        self.assertEqual(NaukriBrowserAdapter.portal_key, "naukri")


if __name__ == "__main__":
    unittest.main()
