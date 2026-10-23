"""QA Easy Apply must reach one phone-step form without live submission."""
import io
import json
import sqlite3
import sys
import tempfile
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


def local_debug_db(path):
    # Minimal ledger fixture. The production debug reader is read-only.
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE applications "
            "(source TEXT, external_id TEXT, url TEXT, status TEXT)"
        )
        conn.execute(
            "INSERT INTO applications VALUES (?,?,?,?)",
            ("linkedin", "4461542106",
             "https://www.linkedin.com/jobs/view/4461542106/", "APPLIED"),
        )


class NonSubmittingDebugTests(unittest.TestCase):
    def test_exact_applied_job_never_reads_private_files_or_opens_browser(self):
        with tempfile.TemporaryDirectory() as temp:
            db = str(Path(temp) / "jobs.db")
            local_debug_db(db)
            with patch("easy_apply_debug._safe_json") as private, \
                 patch("easy_apply_debug.PlaywrightSession") as browser, \
                 redirect_stdout(io.StringIO()) as out:
                code = easy_apply_debug.debug_easy_apply(args(
                    db=db,
                    job_url="https://www.linkedin.com/jobs/view/4461542106/"
                ))
            result = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "debug_already_applied_skipped")
            self.assertEqual(result["attempted"], 0)
            self.assertFalse(result["browser_started"])
            private.assert_not_called()
            browser.assert_not_called()

    def test_db_read_failure_stops_debug_without_browser(self):
        with tempfile.TemporaryDirectory() as temp:
            db = str(Path(temp) / "missing.db")
            with patch("easy_apply_debug._safe_json") as private, \
                 patch("easy_apply_debug.PlaywrightSession") as browser, \
                 redirect_stdout(io.StringIO()) as out:
                code = easy_apply_debug.debug_easy_apply(args(
                    db=db, job_url="https://www.linkedin.com/jobs/view/4461542106/"
                ))
            self.assertEqual(code, 4)
            self.assertEqual(json.loads(out.getvalue())["status"],
                             "debug_ledger_unavailable")
            private.assert_not_called()
            browser.assert_not_called()
            self.assertFalse(Path(db).exists())

    def test_search_skips_applied_candidate_and_previews_only_new_job(self):
        with tempfile.TemporaryDirectory() as temp:
            db = str(Path(temp) / "jobs.db")
            local_debug_db(db)
            runtime = MagicMock()
            adapter = MagicMock()
            adapter.login_state.return_value = SimpleNamespace(
                authenticated=True, needs_human_action=False, reason=""
            )
            adapter.extract_search_results.return_value = [
                job(4461542106), job(4477889900)
            ]
            flow = SimpleNamespace(
                state="NO_SAFE_NEXT_ACTION",
                reasons=("safe_next_control_not_found",),
                steps_completed=0,
            )
            with patch("easy_apply_debug._safe_json", return_value={}), \
                 patch("easy_apply_debug.PlaywrightSession", return_value=runtime), \
                 patch("easy_apply_debug.LinkedInBrowserAdapter",
                       return_value=adapter), \
                 patch("easy_apply_debug.bounded_goto") as nav, \
                 patch("easy_apply_debug.inspect_linkedin_application_entry",
                       side_effect=[
                           entry(state="APPLICATION_ENTRY_FOUND"),
                           entry(state="FORM_READY"),
                       ]) as inspect, \
                 patch("easy_apply_debug.run_safe_application_flow",
                       return_value=flow), \
                 patch("easy_apply_debug.capture_blocker",
                       return_value="saved.blocker.json"), \
                 patch("easy_apply_debug.hold_blocked_browser"), \
                 patch("easy_apply_debug.trace_event"), \
                 redirect_stdout(io.StringIO()) as out:
                code = easy_apply_debug.debug_easy_apply(
                    args(db=db, max_jobs=2, debug_hold_seconds=0)
                )
            self.assertEqual(code, 0)
            nav.assert_called_once_with(runtime.__enter__.return_value.page,
                                        "https://www.linkedin.com/jobs/view/4477889900/")
            self.assertEqual(inspect.call_count, 2)
            result = json.loads(out.getvalue())
            self.assertEqual(result["job_key"], "linkedin:4477889900")
            self.assertEqual(result["attempted"], 0)
            self.assertEqual(result["confirmed"], 0)

    def test_portal_applied_exact_job_never_opens_easy_apply(self):
        runtime = MagicMock()
        runtime.__enter__.return_value.page.url = (
            "https://www.linkedin.com/jobs/view/4480053196/"
        )
        adapter = MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False, reason=""
        )
        with patch("easy_apply_debug._safe_json", return_value={}), \
             patch("easy_apply_debug.PlaywrightSession", return_value=runtime), \
             patch("easy_apply_debug.LinkedInBrowserAdapter", return_value=adapter), \
             patch("easy_apply_debug.bounded_goto"), \
             patch("easy_apply_debug._portal_job_already_applied",
                   return_value=True), \
             patch("easy_apply_debug.inspect_linkedin_application_entry") as entry, \
             patch("easy_apply_debug.run_safe_application_flow") as flow, \
             redirect_stdout(io.StringIO()) as out:
            code = easy_apply_debug.debug_easy_apply(args(
                job_url="https://www.linkedin.com/jobs/view/4480053196/"
            ))
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out.getvalue())["status"],
            "debug_portal_already_applied_skipped",
        )
        entry.assert_not_called()
        flow.assert_not_called()

    def test_portal_applied_search_candidate_skipped(self):
        runtime = MagicMock()
        adapter = MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False, reason=""
        )
        adapter.extract_search_results.return_value = [
            job(4480053196), job(4482222222)
        ]
        flow = SimpleNamespace(
            state="NO_SAFE_NEXT_ACTION",
            reasons=("safe_next_control_not_found",), steps_completed=0
        )
        with patch("easy_apply_debug._safe_json", return_value={}), \
             patch("easy_apply_debug.PlaywrightSession", return_value=runtime), \
             patch("easy_apply_debug.LinkedInBrowserAdapter",
                   return_value=adapter), \
             patch("easy_apply_debug._portal_job_already_applied",
                   side_effect=[True, False]) as applied, \
             patch("easy_apply_debug.bounded_goto") as nav, \
             patch("easy_apply_debug.inspect_linkedin_application_entry",
                   side_effect=[
                       entry(state="APPLICATION_ENTRY_FOUND"),
                       entry(state="FORM_READY"),
                   ]) as inspect, \
             patch("easy_apply_debug.run_safe_application_flow",
                   return_value=flow), \
             patch("easy_apply_debug.capture_blocker",
                   return_value="saved.blocker.json"), \
             patch("easy_apply_debug.hold_blocked_browser"), \
             patch("easy_apply_debug.trace_event"), \
             redirect_stdout(io.StringIO()) as out:
            code = easy_apply_debug.debug_easy_apply(
                args(max_jobs=2, debug_hold_seconds=0)
            )
        self.assertEqual(code, 0)
        self.assertEqual(applied.call_count, 2)
        self.assertEqual(nav.call_count, 2)
        self.assertEqual(inspect.call_count, 2)
        self.assertEqual(json.loads(out.getvalue())["job_key"],
                         "linkedin:4482222222")

    def test_mode_rejects_all_live_submit_or_schedule_override_flags(self):
        for bad in (
            dict(approve_one_live_application=True),
            dict(allow_outside_window=True),
            dict(portal="naukri"),
        ):
            with self.subTest(bad=bad), \
                 patch("easy_apply_debug.PlaywrightSession") as browser, \
                 redirect_stdout(io.StringIO()) as output:
                exit_code = easy_apply_debug.debug_easy_apply(args(**bad))
            self.assertEqual(exit_code, 2)
            self.assertEqual(json.loads(output.getvalue())["confirmed"], 0)
            browser.assert_not_called()

    def test_exact_firework_job_skips_search_and_cannot_switch_listings(self):
        runtime = MagicMock()
        runtime.__enter__.return_value.page.url = "https://www.linkedin.com/jobs/view/4461542106/"
        adapter = MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False, reason=""
        )
        flow = SimpleNamespace(
            state="NEXT_NO_TRANSITION",
            reasons=("live_submission_disabled", "easy_apply_progress_unchanged:1/6 pages"),
            steps_completed=0,
        )
        with patch("easy_apply_debug._safe_json", return_value={}), patch("easy_apply_debug.PlaywrightSession", return_value=runtime), patch("easy_apply_debug.LinkedInBrowserAdapter", return_value=adapter), patch("easy_apply_debug.bounded_goto") as nav, patch("easy_apply_debug.ensure_exact_target") as identity, patch("easy_apply_debug.inspect_linkedin_application_entry", side_effect=[entry(state="APPLICATION_ENTRY_FOUND"), entry(state="FORM_READY")]) as inspect, patch("easy_apply_debug.run_safe_application_flow", return_value=flow) as runner, patch("easy_apply_debug.capture_blocker", return_value="saved.blocker.json"), patch("easy_apply_debug.hold_blocked_browser"), patch("easy_apply_debug.trace_event"), patch("job_agent_cli.run_linkedin_application") as submitter, redirect_stdout(io.StringIO()) as output:
            code = easy_apply_debug.debug_easy_apply(args(job_url="https://www.linkedin.com/jobs/view/4461542106/"))
        self.assertEqual(code, 0)
        nav.assert_called_once_with(runtime.__enter__.return_value.page, "https://www.linkedin.com/jobs/view/4461542106/")
        identity.assert_called_once()
        adapter.open_search.assert_not_called()
        adapter.extract_search_results.assert_not_called()
        self.assertEqual(inspect.call_count, 2)
        self.assertEqual(runner.call_count, 1)
        self.assertTrue(runner.call_args.kwargs["verified_easy_apply_modal"])
        self.assertFalse(runner.call_args.kwargs["live_submission_enabled"])
        submitter.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result["job_key"], "linkedin:4461542106")
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(result["confirmed"], 0)

    def test_exact_debug_review_state_remains_non_submitting(self):
        runtime, adapter = MagicMock(), MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False, reason=""
        )
        review = SimpleNamespace(
            state="REVIEW_INSPECTED",
            reasons=("live_submission_disabled",),
            steps_completed=4,
        )
        with patch("easy_apply_debug._safe_json", return_value={}), \
             patch("easy_apply_debug.PlaywrightSession", return_value=runtime), \
             patch("easy_apply_debug.LinkedInBrowserAdapter", return_value=adapter), \
             patch("easy_apply_debug.bounded_goto"), \
             patch("easy_apply_debug.ensure_exact_target"), \
             patch("easy_apply_debug.inspect_linkedin_application_entry",
                   side_effect=[
                       entry(state="APPLICATION_ENTRY_FOUND"),
                       entry(state="FORM_READY"),
                   ]), \
             patch("easy_apply_debug.run_safe_application_flow",
                   return_value=review) as runner, \
             patch("easy_apply_debug.capture_blocker", return_value="review.blocker.json"), \
             patch("easy_apply_debug.hold_blocked_browser"), \
             patch("easy_apply_debug.trace_event"), \
             patch("job_agent_cli.run_linkedin_application") as submitter, \
             redirect_stdout(io.StringIO()) as out:
            result_code = easy_apply_debug.debug_easy_apply(args(
                job_url="https://www.linkedin.com/jobs/view/4461542106/"
            ))
        self.assertEqual(result_code, 0)
        self.assertTrue(runner.call_args.kwargs["inspect_review"])
        self.assertFalse(runner.call_args.kwargs["live_submission_enabled"])
        submitter.assert_not_called()
        result = json.loads(out.getvalue())
        self.assertEqual(result["flow_state"], "REVIEW_INSPECTED")
        self.assertEqual(result["steps_completed"], 4)
        self.assertFalse(result["submission_enabled"])
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(result["confirmed"], 0)

    def test_debug_checks_live_submit_resolver_but_never_clicks(self):
        runtime, adapter = MagicMock(), MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False, reason=""
        )
        flow = SimpleNamespace(
            state="REVIEW_INSPECTED", reasons=(), steps_completed=4,
        )
        visible_submit = MagicMock()
        with patch("easy_apply_debug._safe_json", return_value={}), \
             patch("easy_apply_debug.PlaywrightSession", return_value=runtime), \
             patch("easy_apply_debug.LinkedInBrowserAdapter", return_value=adapter), \
             patch("easy_apply_debug.bounded_goto"), \
             patch("easy_apply_debug.ensure_exact_target"), \
             patch("easy_apply_debug.inspect_linkedin_application_entry",
                   side_effect=[
                       entry(state="APPLICATION_ENTRY_FOUND"),
                       entry(state="FORM_READY"),
                   ]), \
             patch("easy_apply_debug.run_safe_application_flow",
                   return_value=flow), \
             patch("easy_apply_debug._active_dialog_root", return_value=""), \
             patch("easy_apply_debug._verified_inline_linkedin_final_review",
                   return_value=True) as check, \
             patch("easy_apply_debug._visible_submit_control",
                   return_value=(visible_submit, "Submit application")) as locate, \
             patch("easy_apply_debug.capture_blocker", return_value="review.json"), \
             patch("easy_apply_debug.hold_blocked_browser"), \
             patch("easy_apply_debug.trace_event"), \
             redirect_stdout(io.StringIO()) as output:
            code = easy_apply_debug.debug_easy_apply(
                args(job_url="https://www.linkedin.com/jobs/view/4461542106/")
            )
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["submit_resolver_ready"])
        check.assert_called_once()
        locate.assert_called_once()
        visible_submit.click.assert_not_called()

    def test_unverified_final_page_debug_never_touches_submit(self):
        runtime, adapter = MagicMock(), MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False, reason=""
        )
        flow = SimpleNamespace(
            state="REVIEW_INSPECTED", reasons=(), steps_completed=4,
        )
        with patch("easy_apply_debug._safe_json", return_value={}), \
             patch("easy_apply_debug.PlaywrightSession", return_value=runtime), \
             patch("easy_apply_debug.LinkedInBrowserAdapter", return_value=adapter), \
             patch("easy_apply_debug.bounded_goto"), \
             patch("easy_apply_debug.ensure_exact_target"), \
             patch("easy_apply_debug.inspect_linkedin_application_entry",
                   side_effect=[
                       entry(state="APPLICATION_ENTRY_FOUND"),
                       entry(state="FORM_READY"),
                   ]), \
             patch("easy_apply_debug.run_safe_application_flow",
                   return_value=flow), \
             patch("easy_apply_debug._active_dialog_root", return_value=""), \
             patch("easy_apply_debug._verified_inline_linkedin_final_review",
                   return_value=False), \
             patch("easy_apply_debug._visible_submit_control") as locate, \
             patch("easy_apply_debug.capture_blocker", return_value="review.json"), \
             patch("easy_apply_debug.hold_blocked_browser"), \
             patch("easy_apply_debug.trace_event"), \
             redirect_stdout(io.StringIO()) as output:
            code = easy_apply_debug.debug_easy_apply(
                args(job_url="https://www.linkedin.com/jobs/view/4461542106/")
            )
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output.getvalue())["submit_resolver_ready"])
        locate.assert_not_called()

    def test_invalid_exact_target_blocks_before_reading_private_profile(self):
        with patch("easy_apply_debug._safe_json") as private, patch("easy_apply_debug.PlaywrightSession") as browser, redirect_stdout(io.StringIO()) as output:
            code = easy_apply_debug.debug_easy_apply(args(job_url="https://malicious.example/jobs/view/4461542106/"))
        self.assertEqual(code, 2)
        private.assert_not_called()
        browser.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "invalid_exact_job_target")

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
            reasons=("live_submission_disabled", "safe_next_control_not_found"),
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
        self.assertTrue(runner.call_args.kwargs["inspect_review"])
        self.assertTrue(runner.call_args.kwargs["advance"])
        submitter.assert_not_called()
        self.assertEqual(capture.call_args.kwargs["outcome"], "NO_SAFE_NEXT_ACTION")
        self.assertEqual(capture.call_args.kwargs["reason_code"], "safe_next_control_not_found")
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
