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

    def test_browser_probe_handles_screenshot_layout_and_ignores_sidebar(self):
        """Execute actual JS against a small DOM fixture, not a mocked return."""
        if not shutil.which("node"):
            self.skipTest("Node.js unavailable")
        fixture = r"""
const fs = require('fs');
const source = fs.readFileSync(0, 'utf8');
const mode = process.argv[1];
const main = {kind:'main'};
function el(text, x, y, parent, extra={}) {
  return {
    isConnected:true, disabled:false, parentElement:parent || null,
    innerText:text, textContent:text, value:'',
    getAttribute(){return '';},
    getBoundingClientRect(){return {left:x, top:y, width:240, height:28};},
    closest(){return extra.main || main;},
    querySelectorAll(){return [];},
    contains(other){return this === other;}
  };
}
const title = el('Customer Retention Manager', 113, 260, null);
const x = mode === 'sidebar' ? 948 : 113;
const card = el('Application status Application submitted 21 hours ago View resume',
                x, 650, null);
card.getBoundingClientRect = () => ({left:x,top:635,width:790,height:130});
const label = el('Application status',x,659,card);
const submitted = el('Application submitted',x + 40,700,card);
const resume = el('View resume',x + 40,733,card);
card.querySelectorAll = selector =>
  selector.includes('a, button') ?
    (mode === 'noresume' ? [] : [resume]) : [label, submitted];
global.getComputedStyle = () => ({display:'block',visibility:'visible'});
global.document = {
  querySelectorAll(selector) {
    if (selector === 'h1') return [title];
    if (selector.includes('h2, h3, h4, h5')) return [label];
    return [];
  }
};
const result = eval('(' + source + ')')();
process.stdout.write(JSON.stringify(result));
"""
        for mode, expected_applied in (
            ("sibling", True), ("sidebar", False), ("noresume", False),
        ):
            with self.subTest(mode=mode):
                run = subprocess.run(
                    ["node", "-e", fixture, mode], input=_APPLIED_PROBE,
                    text=True, capture_output=True, check=False, timeout=10,
                )
                self.assertEqual(run.returncode, 0, run.stderr)
                result = json.loads(run.stdout)
                self.assertEqual(result["applied"], expected_applied)
                if expected_applied:
                    self.assertEqual(
                        result["evidence"], "exact_job_sibling_application_status"
                    )
                else:
                    self.assertTrue(result["ambiguous_unscoped_status"])

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
