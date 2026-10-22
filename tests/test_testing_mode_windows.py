"""QA pilots may run outside production windows, never without approval."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import job_agent_cli
from automation_policy import load_automation_policy
from quota import QuotaStatus

LOCAL_OUTSIDE_WINDOW = datetime(2026, 10, 22, 18, 12, tzinfo=ZoneInfo("Asia/Kolkata"))
TARGET_URL = "https://www.linkedin.com/jobs/view/4461542106/"


def cli_args(*, testing_mode=False, approved=False, job_url=TARGET_URL):
    return SimpleNamespace(
        debug_easy_apply_only=False, diagnose_linkedin_page=False,
        inspect_job_only=False, portal="linkedin", job_url=job_url,
        testing_mode=testing_mode, approve_one_live_application=approved,
        allow_outside_window=False, policy="config/automation_policy.production.json",
        db="data/jobs.db",
    )


class TestingWindowTests(unittest.TestCase):
    def setUp(self):
        self.policy = load_automation_policy(
            str(Path(__file__).resolve().parents[1] /
                "config/automation_policy.production.json")
        )

    def test_production_outside_window_still_blocked(self):
        quota = QuotaStatus(
            allowed=False, reason="outside_application_window",
            active_window="", remaining_day=99,
        )
        with patch("job_agent_cli.evaluate_application_quota", return_value=quota), \
             patch("job_agent_cli.trace_event"):
            status = job_agent_cli._pilot_quota_preflight(
                self.policy, MagicMock(), now=LOCAL_OUTSIDE_WINDOW
            )
        self.assertEqual(status["status"], "outside_application_window")
        self.assertEqual(status["attempted"], 0)

    def test_test_mode_outside_window_allowed_but_daily_cap_remains(self):
        quota = QuotaStatus(
            allowed=False, reason="outside_application_window",
            active_window="", daily_confirmed=0, remaining_day=100,
        )
        with patch("job_agent_cli.evaluate_application_quota", return_value=quota) as evaluate, \
             patch("job_agent_cli.trace_event") as event:
            status = job_agent_cli._pilot_quota_preflight(
                self.policy, MagicMock(), testing_mode=True,
                now=LOCAL_OUTSIDE_WINDOW
            )
        self.assertIsNone(status)
        evaluate.assert_called_once()
        self.assertTrue(any(
            call.args[0] == "testing_mode_preflight"
            and call.kwargs["production_time_window_ignored"] is True
            for call in event.call_args_list
        ))

    def test_test_mode_daily_limit_cannot_be_bypassed(self):
        quota = QuotaStatus(
            allowed=False, reason="outside_application_window",
            active_window="", daily_confirmed=100, remaining_day=0,
        )
        with patch("job_agent_cli.evaluate_application_quota", return_value=quota), \
             patch("job_agent_cli.trace_event"):
            status = job_agent_cli._pilot_quota_preflight(
                self.policy, MagicMock(), testing_mode=True,
                now=LOCAL_OUTSIDE_WINDOW
            )
        self.assertEqual(status["status"], "daily_success_cap_reached")
        self.assertEqual(status["attempted"], 0)
        self.assertEqual(status["confirmed"], 0)

    def test_test_mode_requires_exact_job_before_any_live_attempt(self):
        with patch("job_agent_cli.load_automation_policy") as policy_load, \
             patch("job_agent_cli.PlaywrightSession") as browser, \
             patch("job_agent_cli.trace_event"), \
             redirect_stdout(io.StringIO()) as stream:
            code = job_agent_cli._run(cli_args(
                testing_mode=True, approved=True, job_url=""
            ))
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(stream.getvalue())["status"],
            "testing_mode_requires_exact_linkedin_job",
        )
        policy_load.assert_not_called()
        browser.assert_not_called()

    def test_even_testing_mode_does_not_authorize_submission_without_approval(self):
        with patch("job_agent_cli.load_automation_policy") as policy_load, \
             patch("job_agent_cli.PlaywrightSession") as browser, \
             patch("job_agent_cli.trace_event"), \
             redirect_stdout(io.StringIO()) as stream:
            code = job_agent_cli._run(cli_args(testing_mode=True, approved=False))
        self.assertEqual(code, 3)
        self.assertEqual(
            json.loads(stream.getvalue())["status"],
            "single_pilot_approval_required",
        )
        policy_load.assert_not_called()
        browser.assert_not_called()

    def test_production_mode_does_not_implicitly_skip_schedule(self):
        with patch("job_agent_cli.load_automation_policy", return_value=self.policy), \
             patch("job_agent_cli.JobStore") as store, \
             patch("job_agent_cli._pilot_quota_preflight",
                   return_value={"status": "outside_application_window"}) as preflight, \
             patch("job_agent_cli.PlaywrightSession") as browser, \
             patch("job_agent_cli.trace_event"), \
             redirect_stdout(io.StringIO()):
            code = job_agent_cli._run(cli_args(testing_mode=False, approved=True))
        self.assertEqual(code, 5)
        self.assertFalse(preflight.call_args.kwargs["testing_mode"])
        browser.assert_not_called()

    def test_parser_exposes_explicit_testing_switch_without_implicit_approval(self):
        with patch.object(sys, "argv", [
            "job_agent_cli.py", "--testing-mode",
            "--job-url", TARGET_URL,
        ]):
            parsed = job_agent_cli.parse_args()
        self.assertTrue(parsed.testing_mode)
        self.assertFalse(parsed.approve_one_live_application)
        self.assertFalse(parsed.allow_outside_window)
        with patch.object(sys, "argv", ["job_agent_cli.py"]):
            normal = job_agent_cli.parse_args()
        self.assertFalse(normal.testing_mode)


if __name__ == "__main__":
    unittest.main()
