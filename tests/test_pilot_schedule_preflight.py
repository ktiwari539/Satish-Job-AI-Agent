"""No logged-in browser work or private file read is allowed outside quota windows."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_policy import ApplicationWindow, AutomationPolicy
from job_agent_cli import _pilot_quota_preflight, _run


TZ = ZoneInfo("Asia/Kolkata")


def time_at(hour, minute=0, day=21):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def policy():
    return AutomationPolicy(
        timezone="Asia/Kolkata",
        threshold=75, daily_success_cap=100,
        count_only_confirmed_submissions=True, stop_at_window_end=True,
        windows=(
            ApplicationWindow("morning", time(10), time(12), 50),
            ApplicationWindow("night", time(23), time(1), 50),
        ),
        sign_in_if_needed=True, create_account_if_missing=True,
        reuse_email_across_portals=True, allow_configured_password_reuse=True,
        credentials_source="local_secret_only", duplicate_cooldown_days=90,
        live_submission_enabled=True,
    )


class EmptyStore:
    def count_confirmed_submissions(self, **kwargs):
        return 0

    def submission_budget(self, policy, *, now=None):
        # This scheduling fixture has no outstanding reservations. The real
        # SQLite reservation/hold behavior is tested in test_application_queue.
        count=self.count_confirmed_submissions()
        return dict(day=dict(confirmed=count,held=0,used=count),
            window=dict(confirmed=count,held=0,used=count),
            remaining_day=policy.remaining_for_day(count),remaining_window=policy.remaining_for_window(count,now))


class PilotSchedulePreflightTests(unittest.TestCase):
    def test_exact_production_failure_at_0902_is_caught_before_browser(self):
        blocked = _pilot_quota_preflight(policy(), EmptyStore(), now=time_at(9, 2))
        self.assertEqual(blocked["status"], "outside_application_window")
        self.assertEqual(blocked["stage"], "quota_preflight")
        self.assertEqual(blocked["attempted"], 0)
        self.assertEqual(blocked["discovered"], 0)
        self.assertEqual(blocked["next_window"], "morning")
        self.assertEqual(blocked["next_window_start"], "2026-10-21T10:00:00+05:30")

    def test_exact_10am_allowed_and_no_early_approval(self):
        self.assertIsNone(_pilot_quota_preflight(policy(), EmptyStore(), now=time_at(10)))
        self.assertIsNone(_pilot_quota_preflight(policy(), EmptyStore(), now=time_at(11, 59)))

    def test_end_boundary_denied_then_next_night_window(self):
        blocked = _pilot_quota_preflight(policy(), EmptyStore(), now=time_at(12))
        self.assertEqual(blocked["next_window"], "night")
        self.assertEqual(blocked["next_window_start"], "2026-10-21T23:00:00+05:30")
        self.assertEqual(blocked["next_window_end"], "2026-10-22T01:00:00+05:30")

    def test_night_window_crosses_midnight(self):
        self.assertIsNone(_pilot_quota_preflight(policy(), EmptyStore(), now=time_at(0, 30)))
        blocked = _pilot_quota_preflight(policy(), EmptyStore(), now=time_at(1))
        self.assertEqual(blocked["next_window"], "morning")
        self.assertEqual(blocked["next_window_start"], "2026-10-21T10:00:00+05:30")

    def test_quota_caps_still_block_inside_allowed_window(self):
        class FullStore(EmptyStore):
            def count_confirmed_submissions(self, **kwargs):
                return 100
        result = _pilot_quota_preflight(policy(), FullStore(), now=time_at(10, 5))
        self.assertEqual(result["status"], "daily_success_cap_reached")
        self.assertNotIn("next_window_start", result)

    def test_preflight_blocks_private_data_and_chrome_before_opening(self):
        args = SimpleNamespace(
            job_url="https://www.linkedin.com/jobs/view/9000000001/",
            approve_one_live_application=True,
            allow_outside_window=False,
            policy="test.json", db="test.db",
        )
        output = io.StringIO()
        with patch("job_agent_cli.load_automation_policy", return_value=policy()), \
             patch("job_agent_cli.JobStore", return_value=EmptyStore()), \
             patch("job_agent_cli._load_json", side_effect=AssertionError("private data read")) as private_read, \
             patch("job_agent_cli.PlaywrightSession", side_effect=AssertionError("browser opened")) as browser, \
             patch("job_agent_cli.resolve_current_resume", side_effect=AssertionError("resume read")) as resume, \
             patch("job_agent_cli.evaluate_application_quota") as quota:
            from quota import QuotaStatus
            quota.return_value = QuotaStatus(
                allowed=False, reason="outside_application_window",
                remaining_day=100,
            )
            with patch("job_agent_cli.trace_event"):
                with redirect_stdout(output):
                    code = _run(args)
        self.assertEqual(code, 5)
        private_read.assert_not_called()
        browser.assert_not_called()
        resume.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "outside_application_window")
        self.assertEqual(result["discovered"], 0)

    def test_explicit_qa_flag_skips_preflight_but_does_not_change_policy(self):
        with patch("job_agent_cli.evaluate_application_quota",
                   side_effect=AssertionError("quota invoked")):
            self.assertIsNone(_pilot_quota_preflight(
                policy(), EmptyStore(), allow_outside_window=True, now=time_at(9, 2)
            ))


if __name__ == "__main__":
    unittest.main()
