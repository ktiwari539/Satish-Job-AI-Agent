"""Regression tests for read-only, privacy-limited exact-job DOM diagnosis."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import job_agent_cli
from linkedin_page_diagnostics import _validate_signals, diagnose_linkedin_search_page
from linkedin_exact_job import parse_linkedin_target


URL = ("https://www.linkedin.com/jobs/search-results/"
       "?currentJobId=4476701830&keywords=Customer%20Success%20Manager"
       "&geoId=90009639")
TARGET = parse_linkedin_target(URL)


class Page:
    def __init__(self, signals=None):
        self.url = ("https://www.linkedin.com/jobs/search-results/"
                    "?currentJobId=4476701830")
        self.signals = signals or {}
        self.eval_calls = []
        self.waits = 0
        self.click_calls = 0

    def wait_for_timeout(self, milliseconds):
        self.waits += 1

    def evaluate(self, code, target_id):
        self.eval_calls.append(target_id)
        return self.signals

    def click(self, *args, **kwargs):
        self.click_calls += 1
        raise AssertionError("read-only diagnosis cannot click")


class PageDiagnosisTests(unittest.TestCase):
    def test_no_job_cards_diagnosed_without_copying_user_text(self):
        raw = {
            "body_chars": 10519, "ready_complete": True,
            "route_search": True, "main_count": 1,
            "scaffold_cards": 0, "results_cards": 0,
            "container_cards": 0, "job_links": 0,
            "exact_job_links": 0, "job_id_nodes": 0,
            "exact_job_id_nodes": 0,
            "user_email": "private@example.invalid",
            "page_html": "<secret>user info</secret>",
        }
        page = Page(raw)
        with patch("linkedin_page_diagnostics.bounded_goto"):
            result = diagnose_linkedin_search_page(
                page, TARGET, source_url=URL, keywords="Customer Success Manager"
            )
        self.assertEqual(result["diagnosis"], "search_page_without_job_markup")
        self.assertEqual(result["body_chars"], 10519)
        self.assertNotIn("user_email", result)
        self.assertNotIn("page_html", result)
        self.assertNotIn("private@example.invalid", str(result))
        self.assertEqual(page.eval_calls, ["4476701830"])
        self.assertEqual(page.click_calls, 0)

    def test_exact_job_link_without_known_css_reports_selector_mismatch(self):
        result = _validate_signals({
            "body_chars": 12000, "route_search": True,
            "exact_job_links": 1, "job_links": 5,
        })
        self.assertEqual(result["diagnosis"], "exact_job_dom_present_selector_mismatch")

    def test_other_jobs_present_cannot_be_treated_as_selected_job(self):
        result = _validate_signals({
            "body_chars": 9000, "route_search": True,
            "job_links": 12, "exact_job_links": 0,
        })
        self.assertEqual(result["diagnosis"], "other_job_dom_present_target_missing")

    def test_challenge_state_takes_priority_and_is_not_bypassed(self):
        result = _validate_signals({
            "body_chars": 500, "route_search": True,
            "job_links": 1, "challenge_hint": True,
        })
        self.assertEqual(result["diagnosis"], "challenge_detected")

    def test_diagnostic_route_mismatch_blocks_without_evaluation(self):
        page = Page()
        page.url = "https://www.linkedin.com/jobs/search/?currentJobId=4477371718"
        with patch("linkedin_page_diagnostics.bounded_goto"):
            with self.assertRaisesRegex(ValueError, "route_changed"):
                diagnose_linkedin_search_page(page, TARGET,
                                              source_url=URL, keywords="Customer Success Manager")
        self.assertEqual(page.eval_calls, [])
        self.assertEqual(page.click_calls, 0)

    def test_malformed_probe_payload_is_not_reflected(self):
        self.assertEqual(_validate_signals("secret-string"), {"diagnosis": "probe_unavailable"})
        result = _validate_signals({
            "body_chars": "SECRET", "route_search": "yes",
            "unexpected": "private-profile-data",
        })
        self.assertNotIn("private-profile-data", str(result))
        self.assertEqual(result["body_chars"], 0)
        self.assertFalse(result["route_search"])


class DiagnosticCLITests(unittest.TestCase):
    def test_new_arg_requires_no_submit_approval(self):
        with patch.object(sys, "argv", [
            "job_agent_cli.py", "--portal", "linkedin", "--job-url", URL,
            "--diagnose-linkedin-page",
        ]):
            args = job_agent_cli.parse_args()
        self.assertTrue(args.diagnose_linkedin_page)
        self.assertFalse(args.approve_one_live_application)

    def test_mode_does_not_read_any_profile_or_run_applications(self):
        args = SimpleNamespace(
            diagnose_linkedin_page=True, portal="linkedin", job_url=URL,
            profile_dir="browser-profile", headless=False, query="Customer Success Manager",
        )
        runtime = MagicMock()
        adapter = MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False, reason="",
        )
        expected = {"diagnosis": "search_page_without_job_markup"}
        with patch("job_agent_cli._load_json", side_effect=AssertionError("profile was read")) as profile, \
             patch("job_agent_cli.JobStore", side_effect=AssertionError("db opened")) as store, \
             patch("job_agent_cli.resolve_current_resume", side_effect=AssertionError("resume read")) as resume, \
             patch("job_agent_cli.PlaywrightSession", return_value=runtime), \
             patch("job_agent_cli.LinkedInBrowserAdapter", return_value=adapter), \
             patch("job_agent_cli.diagnose_linkedin_search_page", return_value=expected) as probe, \
             patch("job_agent_cli.run_linkedin_application", side_effect=AssertionError("application attempted")) as apply, \
             patch("job_agent_cli.trace_event"), \
             redirect_stdout(io.StringIO()) as output:
            code = job_agent_cli._run(args)
        self.assertEqual(code, 0)
        probe.assert_called_once()
        profile.assert_not_called()
        store.assert_not_called()
        resume.assert_not_called()
        apply.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "linkedin_page_diagnosis_complete")
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(result["confirmed"], 0)
        self.assertEqual(result["job_id"], TARGET.job_id)

    def test_invalid_job_url_blocks_before_browser(self):
        args = SimpleNamespace(
            diagnose_linkedin_page=True, portal="linkedin",
            job_url="https://unknown.invalid/", profile_dir="browser-profile",
            headless=False,
        )
        with patch("job_agent_cli.PlaywrightSession") as browser, \
             patch("job_agent_cli.trace_event"), \
             redirect_stdout(io.StringIO()) as output:
            code = job_agent_cli._run(args)
        self.assertEqual(code, 2)
        browser.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["attempted"], 0)


if __name__ == "__main__":
    unittest.main()
