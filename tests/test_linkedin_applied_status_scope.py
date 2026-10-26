"""Exact-job LinkedIn status must never interpret global sidebar text as proof."""
import io
import json
import shutil
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from linkedin_applied_status import _APPLIED_PROBE, inspect_exact_applied_status
import easy_apply_debug


class ExactAppliedStatusScopeTests(unittest.TestCase):
    def test_probe_scopes_application_status_to_current_job_panel(self):
        self.assertIn("exactJobPanels.some(panel", _APPLIED_PROBE)
        self.assertIn("panel.contains(label)", _APPLIED_PROBE)
        self.assertIn("ambiguous_unscoped_status", _APPLIED_PROBE)
        self.assertNotIn("document.body.innerText", _APPLIED_PROBE)

    def test_unscoped_status_is_not_classified_as_applied(self):
        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/4481663953/"
        page.evaluate.return_value = {
            "applied": False, "evidence": "",
            "ambiguous_unscoped_status": True,
        }
        with patch("linkedin_applied_status.ensure_exact_target"):
            result = inspect_exact_applied_status(
                page, SimpleNamespace(job_id="4481663953")
            )
        self.assertEqual(result["status"], "application_status_ambiguous")
        self.assertEqual(
            result["reason"], "submitted_status_not_scoped_to_current_job_panel"
        )

    def test_scoped_applied_status_remains_a_positive_indicator(self):
        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/4481663953/"
        page.evaluate.return_value = {
            "applied": True, "evidence": "exact_job_application_status",
        }
        with patch("linkedin_applied_status.ensure_exact_target"):
            result = inspect_exact_applied_status(
                page, SimpleNamespace(job_id="4481663953")
            )
        self.assertEqual(result["status"], "linkedin_exact_job_applied_visible")
        self.assertEqual(result["evidence_kind"], "exact_job_application_status")

    def test_strongly_scoped_sibling_status_counts_as_applied(self):
        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/4474066157/"
        page.evaluate.return_value = {
            "applied": True, "evidence": "exact_job_sibling_application_status"
        }
        from linkedin_exact_job import parse_linkedin_target
        result = inspect_exact_applied_status(
            page, parse_linkedin_target(page.url)
        )
        self.assertEqual(result["status"], "linkedin_exact_job_applied_visible")
        self.assertEqual(result["evidence_kind"],
                         "exact_job_sibling_application_status")

    def test_screenshot_sibling_status_uses_strong_scope_not_global_text(self):
        self.assertIn("sameJobColumn(label)", _APPLIED_PROBE)
        self.assertIn("resumeLink && sameJobColumn(label)", _APPLIED_PROBE)
        self.assertIn("statusBox.top <= titleBox.top", _APPLIED_PROBE)
        self.assertIn("exact_job_sibling_application_status", _APPLIED_PROBE)
        self.assertNotIn("document.body.innerText", _APPLIED_PROBE)

    def test_ambiguous_status_does_not_open_application(self):
        page = MagicMock()
        runtime = MagicMock()
        runtime.__enter__.return_value.page = page
        adapter = MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False, reason=""
        )
        def ambiguous(_page, _url, *, details=None):
            details.update(status="ambiguous", evidence_kind="none")
            return False

        args = SimpleNamespace(
            portal="linkedin", approve_one_live_application=False,
            allow_outside_window=False,
            job_url="https://www.linkedin.com/jobs/view/4481663953/",
            private_profile="data/private_profile.json",
            profile_dir="browser-profile", headless=False,
            resume_path="", db="data/jobs.db", debug_interactive=True,
        )
        with patch("easy_apply_debug._local_application_already_recorded",
                   return_value=False), \
             patch("easy_apply_debug._safe_json", return_value={}), \
             patch("easy_apply_debug.PlaywrightSession", return_value=runtime), \
             patch("easy_apply_debug.LinkedInBrowserAdapter",
                   return_value=adapter), \
             patch("easy_apply_debug.bounded_goto"), \
             patch("easy_apply_debug.ensure_exact_target"), \
             patch("easy_apply_debug._portal_job_already_applied",
                   side_effect=ambiguous), \
             patch("easy_apply_debug.inspect_linkedin_application_entry") as entry, \
             patch("easy_apply_debug.trace_event"), \
             redirect_stdout(io.StringIO()) as out:
            code = easy_apply_debug.debug_easy_apply(args)
        result = json.loads(out.getvalue())
        self.assertEqual(code, 4)
        self.assertEqual(result["status"], "debug_ambiguous_application_status_blocked")
        self.assertFalse(result["flow_tested"])
        self.assertEqual(result["attempted"], 0)
        entry.assert_not_called()


if __name__ == "__main__":
    unittest.main()
