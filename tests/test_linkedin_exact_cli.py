import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import job_agent_cli
from models import Job


URL = "https://www.linkedin.com/jobs/search-results/?currentJobId=4476701830&keywords=Customer%20Success%20Manager"
CANONICAL = "https://www.linkedin.com/jobs/view/4476701830/"
PROFILE = {
    "target_roles": ["customer success manager"],
    "skills": ["customer success", "sla", "stakeholder management", "onboarding"],
    "skill_taxonomy": ["customer success", "sla", "stakeholder management", "onboarding"],
    "preferred_locations": ["india"],
    "remote_allowed": True, "total_experience_years": 8,
    "india_authorized": True, "outside_india_sponsorship_required": True,
}
JOB = Job(
    "linkedin", "4476701830", "Example Company", "Customer Success Manager",
    "India", CANONICAL, "Customer success SLA onboarding stakeholder management " * 10,
    required_skills=("customer success", "sla", "onboarding", "stakeholder management"),
)


class ExactCLITests(unittest.TestCase):
    def test_arg_parser_supports_read_only_inspection_without_approval(self):
        with patch.object(sys, "argv", ["job_agent_cli.py", "--job-url", URL, "--inspect-job-only"]):
            args = job_agent_cli.parse_args()
        self.assertTrue(args.inspect_job_only)
        self.assertFalse(args.approve_one_live_application)
        self.assertEqual(args.job_url, URL)

    def test_invalid_url_rejected_before_browser(self):
        args = SimpleNamespace(
            inspect_job_only=False, job_url="https://evil.test/job/1",
            portal="linkedin", approve_one_live_application=True,
        )
        with patch("job_agent_cli.PlaywrightSession") as browser, redirect_stdout(io.StringIO()) as out:
            code = job_agent_cli._run(args)
        self.assertEqual(code, 2)
        browser.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())["attempted"], 0)

    def test_read_only_inspection_never_calls_application_engine(self):
        args = SimpleNamespace(
            inspect_job_only=True, job_url=URL, portal="linkedin",
            profile="profile.json", db="db", profile_dir="profile", headless=False,
        )
        runtime = MagicMock()
        runtime.__enter__.return_value.page.url = CANONICAL
        adapter = MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False, reason=""
        )
        store = MagicMock()
        store.is_recent_similar_application.return_value = False
        with patch("job_agent_cli._load_json", return_value=PROFILE) as load, \
             patch("job_agent_cli.JobStore", return_value=store), \
             patch("job_agent_cli.PlaywrightSession", return_value=runtime), \
             patch("job_agent_cli.LinkedInBrowserAdapter", return_value=adapter), \
             patch("job_agent_cli.inspect_exact_linkedin_job", return_value=JOB), \
             patch("job_agent_cli.run_linkedin_application") as application, \
             redirect_stdout(io.StringIO()) as out:
            code = job_agent_cli._run(args)
        self.assertEqual(code, 0)
        self.assertEqual(load.call_count, 1)
        application.assert_not_called()
        result = json.loads(out.getvalue())
        self.assertEqual(result["status"], "exact_job_qualified_for_pilot")
        self.assertEqual(result["job_id"], "4476701830")
        self.assertEqual(result["attempted"], 0)

    def test_single_job_live_dispatch_does_not_search_other_listings(self):
        with tempfile.TemporaryDirectory() as root:
            resume = Path(root) / "resume.docx"
            resume.write_text("test placeholder")
            args = SimpleNamespace(
                inspect_job_only=False, job_url=URL, portal="linkedin",
                approve_one_live_application=True, allow_outside_window=True,
                policy="policy.json", db="db", profile="profile.json",
                private_profile="private.json", resume_path=str(resume),
                credentials_file="credentials.json", profile_dir="browser-profile",
                headless=False, query="unrelated", location="India", max_jobs=200,
                report=str(Path(root) / "report.json"),
            )
            runtime = MagicMock()
            runtime.__enter__.return_value.page.url = CANONICAL
            adapter = MagicMock()
            adapter.login_state.return_value = SimpleNamespace(
                authenticated=True, needs_human_action=False, reason=""
            )
            store = MagicMock()
            store.is_recent_similar_application.return_value = False
            policy = SimpleNamespace(
                live_submission_enabled=True, allow_configured_password_reuse=False,
                duplicate_cooldown_days=90, threshold=75,
            )
            blocked = SimpleNamespace(
                engine_stage="BLOCKED", engine_history=(),
                entry=SimpleNamespace(
                    application_state="FORM_READY", application_type="LINKEDIN_EASY_APPLY",
                    ats_provider="", reason="manual review required",
                ),
                flow=None, submission=None,
            )
            with patch("job_agent_cli.load_automation_policy", return_value=policy), \
                 patch("job_agent_cli.JobStore", return_value=store), \
                 patch("job_agent_cli._load_json", side_effect=[PROFILE, {}]), \
                 patch("job_agent_cli.derive_resume_facts", return_value={}), \
                 patch("job_agent_cli.load_first_portal_credentials",
                       side_effect=FileNotFoundError), \
                 patch("job_agent_cli.PlaywrightSession", return_value=runtime), \
                 patch("job_agent_cli.LinkedInBrowserAdapter", return_value=adapter), \
                 patch("job_agent_cli.inspect_exact_linkedin_job", return_value=JOB) as inspect, \
                 patch("job_agent_cli.bounded_goto"), \
                 patch("job_agent_cli.run_linkedin_application",
                       return_value=blocked) as application, \
                 redirect_stdout(io.StringIO()) as out:
                code = job_agent_cli._run(args)
            self.assertEqual(code, 5)
            adapter.open_search.assert_not_called()
            adapter.extract_search_results.assert_not_called()
            inspect.assert_called_once()
            report = json.loads(Path(args.report).read_text())
            self.assertEqual(report["discovered"], 1)
            self.assertEqual(report["attempted"], 1, str(report.get("outcomes")))
            application.assert_called_once()
            self.assertEqual(report["confirmed"], 0)
            self.assertIn("4476701830", report["outcomes"][0]["job_key"])


if __name__ == "__main__":
    unittest.main()
