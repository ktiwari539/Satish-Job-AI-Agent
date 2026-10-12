import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path as SysPath
from types import SimpleNamespace
from unittest.mock import MagicMock
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

    def test_missing_google_session_never_uses_stored_password(self):
        with patch.object(sys, "argv", ["job_agent_cli.py", "--portal", "naukri"]):
            args = job_agent_cli.parse_args()
        profile = {
            "target_roles": [], "skills": [], "preferred_locations": [],
            "remote_allowed": True, "total_experience_years": 8,
            "india_authorized": True, "outside_india_sponsorship_required": True,
        }
        fake_page = SimpleNamespace(url="https://www.naukri.com/")
        fake_runtime = MagicMock()
        fake_runtime.__enter__.return_value.page = fake_page
        fake_adapter = MagicMock()
        fake_adapter.login_state.return_value = SimpleNamespace(
            authenticated=False, needs_human_action=False,
            reason="naukri_login_required",
        )
        policy = SimpleNamespace(live_submission_enabled=True,
                                 allow_configured_password_reuse=False)
        output = io.StringIO()
        with patch.object(job_agent_cli, "_load_json", side_effect=[profile, {}]), \
             patch.object(job_agent_cli, "load_automation_policy", return_value=policy), \
             patch.object(job_agent_cli, "JobStore"), \
             patch.object(job_agent_cli, "resolve_current_resume", return_value=SysPath("/tmp/trusted.docx")), \
             patch.object(job_agent_cli, "derive_resume_facts", return_value={}), \
             patch.object(job_agent_cli, "load_first_portal_credentials", side_effect=FileNotFoundError), \
             patch.object(job_agent_cli, "PlaywrightSession", return_value=fake_runtime), \
             patch.object(job_agent_cli, "NaukriBrowserAdapter", return_value=fake_adapter), \
             patch.object(job_agent_cli, "load_portal_credentials", side_effect=AssertionError("password fallback forbidden")) as credentials:
            with redirect_stdout(output):
                code = job_agent_cli._run(args)
        self.assertEqual(code, 4)
        self.assertEqual(
            json.loads(output.getvalue().strip())["status"],
            "naukri_google_session_required",
        )
        credentials.assert_not_called()

    def test_naukri_has_independent_adapter(self):
        self.assertEqual(NaukriBrowserAdapter.portal_key, "naukri")


if __name__ == "__main__":
    unittest.main()
