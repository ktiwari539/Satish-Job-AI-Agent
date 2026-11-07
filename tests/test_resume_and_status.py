import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import agent_status
import job_agent_cli


class ResumeAndStatusTests(unittest.TestCase):
    def test_blank_resume_path_fails_before_browser_start(self):
        args = type("Args", (), {
            "profile": "config/qa_profile.json",
            "private_profile": "data/private_profile.json",
            "policy": "config/automation_policy.production.json",
            "credentials_file": "data/portal_credentials.json",
            "profile_dir": "browser-profile",
            "db": "data/jobs.db",
            "report": "data/application_report.json",
            "resume_path": "",
            "query": "Customer Success Manager",
            "location": "India",
            "max_jobs": 1,
            "headless": False,
            "trace_dir": "data/agent_runs",
            "heartbeat_seconds": 5.0,
            "allow_outside_window": True,
            "approve_one_live_application": True,
            "job_url": "https://www.linkedin.com/jobs/view/9000000001/",
        })()

        with patch.object(job_agent_cli, "resolve_current_resume", side_effect=FileNotFoundError("no trusted resume")) as resume_lookup, unittest.mock.patch.object(job_agent_cli, "_load_json", side_effect=[
            {
                "target_roles": [],
                "skills": [],
                "preferred_locations": [],
                "remote_allowed": True,
                "total_experience_years": 8,
                "india_authorized": True,
                "outside_india_sponsorship_required": True,
            },
            {},
        ]), unittest.mock.patch.object(
            job_agent_cli,
            "load_automation_policy",
        ) as policy_loader, unittest.mock.patch.object(
            job_agent_cli,
            "JobStore",
        ):
            policy_loader.return_value.live_submission_enabled = True
            out = io.StringIO()
            with redirect_stdout(out):
                code = job_agent_cli._run(args)

        resume_lookup.assert_called_once_with()
        self.assertEqual(code, 2)
        payload = json.loads(out.getvalue().strip())
        self.assertEqual(payload["status"], "agent_resume_not_configured")
        self.assertIn("resume_vault", payload)

    def test_agent_status_does_not_show_stale_review_blockers(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "agent_status.json").write_text(
                json.dumps({
                    "run_id": "new-run",
                    "status": "failed",
                    "events_file": "data/agent_runs/new.jsonl",
                }),
                encoding="utf-8",
            )
            (base / "review_ready_report.json").write_text(
                json.dumps({
                    "run_id": "old-run",
                    "outcomes": [{
                        "job_key": "old-job",
                        "status": "BLOCKED",
                        "reason": "old blocker",
                    }],
                }),
                encoding="utf-8",
            )
            (base / "agent_latest.jsonl").write_text("", encoding="utf-8")

            out = io.StringIO()
            with redirect_stdout(out):
                agent_status._print_snapshot(base, 5)

            rendered = out.getvalue()
            self.assertIn("No application outcomes belong to the current run.", rendered)
            self.assertNotIn("old-job", rendered)


if __name__ == "__main__":
    unittest.main()
