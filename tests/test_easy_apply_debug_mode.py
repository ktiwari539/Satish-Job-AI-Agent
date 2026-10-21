"""QA Easy Apply must reach one phone-step form without live submission."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import easy_apply_debug
import job_agent_cli


def args(**overrides):
    data = dict(
        portal="linkedin", query="Customer Success Manager", location="India",
        job_url="", max_jobs=20, approve_one_live_application=False,
        allow_outside_window=False, private_profile="local.json",
        resume_path="", profile_dir="browser-profile", headless=False,
        debug_hold_seconds=45, debug_easy_apply_only=True,
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def job(number, title="Customer Success Manager"):
    return SimpleNamespace(
        title=title,
        key="linkedin:" + str(number),
        url="https://www.linkedin.com/jobs/view/" + str(number) + "/",
    )


def entry(kind="LINKEDIN_EASY_APPLY", state="FORM_READY", reason=""):
    return SimpleNamespace(application_type=kind, application_state=state, reason=reason)


class NonSubmittingDebugTests(unittest.TestCase):
    def test_mode_rejects_all_live_submit_or_schedule_override_flags(self):
        for bad in (
            dict(approve_one_live_application=True),
            dict(allow_outside_window=True),
            dict(portal="naukri"),
            dict(job_url="https://www.linkedin.com/jobs/view/4476701830/"),
        ):
            with self.subTest(bad=bad), \
                 patch("easy_apply_debug.PlaywrightSession") as browser, \
                 redirect_stdout(io.StringIO()) as output:
                exit_code = easy_apply_debug.debug_easy_apply(args(**bad))
            self.assertEqual(exit_code, 2)
            self.assertEqual(json.loads(output.getvalue())["confirmed"], 0)
            browser.assert_not_called()

    def test_previews_other_jobs_then_debugs_exactly_one_easy_apply_without_submit(self):
        runtime = MagicMock()
        adapter = MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False, reason=""
        )
        adapter.extract_search_results.return_value = [
            job(1111111111), job(2222222222), job(3333333333)
        ]
        flow = SimpleNamespace(
            state="NO_SAFE_NEXT_ACTION",
            reasons=("safe_next_control_not_found",),
            steps_completed=1,
        )
        with patch("easy_apply_debug._safe_json", return_value={"phone": "private"}), \
             patch("easy_apply_debug.PlaywrightSession", return_value=runtime), \
             patch("easy_apply_debug.LinkedInBrowserAdapter", return_value=adapter), \
             patch("easy_apply_debug.bounded_goto") as navigate, \
             patch("easy_apply_debug.inspect_linkedin_application_entry",
                   side_effect=[
                       entry("EXTERNAL_APPLY", "APPLICATION_ENTRY_FOUND"),
                       entry("LINKEDIN_EASY_APPLY", "APPLICATION_ENTRY_FOUND"),
                       entry("LINKEDIN_EASY_APPLY", "FORM_READY"),
                   ]) as inspect, \
             patch("easy_apply_debug.run_safe_application_flow",
                   return_value=flow) as runner, \
             patch("easy_apply_debug.capture_blocker",
                   return_value="data/agent_runs/test.blocker.json") as capture, \
             patch("easy_apply_debug.hold_blocked_browser") as hold, \
             patch("easy_apply_debug.trace_event"), \
             patch("job_agent_cli.run_linkedin_application") as submitter, \
             redirect_stdout(io.StringIO()) as output:
            exit_code = easy_apply_debug.debug_easy_apply(args(resume_path=""))

        self.assertEqual(exit_code, 0)
        adapter.open_search.assert_called_once_with("Customer Success Manager", "India")
        self.assertEqual(inspect.call_count, 3)
        self.assertEqual(navigate.call_count, 2)
        self.assertEqual(runner.call_count, 1)
        self.assertFalse(runner.call_args.kwargs["live_submission_enabled"])
        self.assertFalse(runner.call_args.kwargs["inspect_review"])
        self.assertTrue(runner.call_args.kwargs["advance"])
        submitter.assert_not_called()
        self.assertEqual(capture.call_args.kwargs["outcome"], "NO_SAFE_NEXT_ACTION")
        self.assertEqual(hold.call_args.args[1], 45)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "easy_apply_debug_complete")
        self.assertEqual(result["confirmed"], 0)
        self.assertEqual(result["attempted"], 0)
        self.assertFalse(result["submission_enabled"])
        self.assertEqual(result["steps_completed"], 1)

    def test_clicked_cta_without_modal_reports_actual_failure_not_next_missing(self):
        runtime, adapter = MagicMock(), MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False, reason=""
        )
        adapter.extract_search_results.return_value = [job(4409454707)]
        with patch("easy_apply_debug._safe_json", return_value={}), \
             patch("easy_apply_debug.PlaywrightSession", return_value=runtime), \
             patch("easy_apply_debug.LinkedInBrowserAdapter", return_value=adapter), \
             patch("easy_apply_debug.bounded_goto"), \
             patch("easy_apply_debug.inspect_linkedin_application_entry",
                   side_effect=[
                       entry(state="APPLICATION_ENTRY_FOUND"),
                       entry(state="FORM_NOT_READY", reason="easy_apply_modal_not_opened"),
                   ]), \
             patch("easy_apply_debug.run_safe_application_flow") as fill, \
             patch("easy_apply_debug.capture_blocker", return_value="saved.blocker.json") as capture, \
             patch("easy_apply_debug.hold_blocked_browser"), \
             patch("easy_apply_debug.trace_event"), \
             redirect_stdout(io.StringIO()) as output:
            code = easy_apply_debug.debug_easy_apply(args())
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["flow_state"], "easy_apply_modal_not_opened")
        self.assertEqual(result["confirmed"], 0)
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(capture.call_args.kwargs["reason_code"], "easy_apply_modal_not_opened")
        fill.assert_not_called()

    def test_missing_easy_apply_stops_without_opening_form(self):
        runtime, adapter = MagicMock(), MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False, reason=""
        )
        adapter.extract_search_results.return_value = [job(1111111111)]
        with patch("easy_apply_debug._safe_json", return_value={}), \
             patch("easy_apply_debug.PlaywrightSession", return_value=runtime), \
             patch("easy_apply_debug.LinkedInBrowserAdapter", return_value=adapter), \
             patch("easy_apply_debug.bounded_goto"), \
             patch("easy_apply_debug.inspect_linkedin_application_entry",
                   return_value=entry("EXTERNAL_APPLY", "APPLICATION_ENTRY_FOUND")), \
             patch("easy_apply_debug.run_safe_application_flow") as fill, \
             redirect_stdout(io.StringIO()) as output:
            code = easy_apply_debug.debug_easy_apply(args())
        self.assertEqual(code, 4)
        fill.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "debug_no_easy_apply_entry")

    def test_cli_debug_routes_before_live_approval_and_preflight(self):
        with patch("job_agent_cli.debug_easy_apply", return_value=0) as debug, \
             patch("job_agent_cli.load_automation_policy") as policy, \
             patch("job_agent_cli._pilot_quota_preflight") as quota, \
             patch("job_agent_cli.trace_event"):
            self.assertEqual(job_agent_cli._run(args()), 0)
        debug.assert_called_once()
        policy.assert_not_called()
        quota.assert_not_called()

    def test_cli_args_are_not_a_live_submission_approval(self):
        with patch.object(sys, "argv", [
            "job_agent_cli.py", "--debug-easy-apply-only",
            "--debug-hold-seconds", "45"
        ]):
            parsed = job_agent_cli.parse_args()
        self.assertTrue(parsed.debug_easy_apply_only)
        self.assertFalse(parsed.approve_one_live_application)
        self.assertFalse(parsed.allow_outside_window)
        self.assertEqual(parsed.debug_hold_seconds, 45)


if __name__ == "__main__":
    unittest.main()
