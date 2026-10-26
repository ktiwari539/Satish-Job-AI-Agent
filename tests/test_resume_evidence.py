"""Selected-resume evidence must be explicit before a live Submit."""
import json
import sys
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from application_forms import FillPlan
from application_flow import run_safe_application_flow
from resume_evidence import _RESUME_PROBE, _expected_names, inspect_resume_evidence


class EvidencePage:
    url = "https://www.linkedin.com/jobs/view/4461542106/"

    def __init__(self, signals=None):
        self.signals = signals
        self.seen_args = None

    def evaluate(self, script, args):
        self.seen_args = args
        return self.signals


class ResumeEvidenceTests(unittest.TestCase):
    def test_manifest_original_name_and_vault_name_are_compared_locally(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "resume-abc123.docx"
            (Path(folder) / "manifest.json").write_text(json.dumps({
                "current_file": p.name,
                "original_name": "Candidate_Resume_2026.docx"
            }))
            self.assertEqual(_expected_names(str(p)), [
                "resume-abc123.docx", "candidate_resume_2026.docx"
            ])

    def test_saved_resume_selected_is_strongest_evidence(self):
        page = EvidencePage({"savedMatch": True, "savedMismatch": False,
                             "localFileSelected": False})
        result = inspect_resume_evidence(page, "/fake/resume-abc.docx")
        self.assertEqual(result, "matching_resume_selected")
        self.assertEqual(page.seen_args["names"], ["resume-abc.docx"])

    def test_wrong_selected_resume_blocks_even_if_local_input_matches(self):
        page = EvidencePage({"savedMatch": True, "savedMismatch": True,
                             "localFileSelected": True})
        self.assertEqual(inspect_resume_evidence(page, "/fake/resume.docx"),
                         "different_resume_selected")

    def test_file_input_selection_is_not_server_attachment_proof(self):
        page = EvidencePage({"savedMatch": False, "savedMismatch": False,
                             "localFileSelected": True})
        self.assertEqual(inspect_resume_evidence(page, "/fake/resume.docx"),
                         "file_input_selected_unconfirmed")

    def test_no_dom_evidence_never_implies_attached(self):
        self.assertEqual(inspect_resume_evidence(EvidencePage(None), "/fake/resume.docx"),
                         "attachment_unverified")
        self.assertEqual(inspect_resume_evidence(EvidencePage({}), ""),
                         "no_resume_configured")

    def test_inline_resume_probe_is_scoped_and_valid_javascript(self):
        self.assertIn("const pageCounters", _RESUME_PROBE)
        self.assertIn("inlineWizard", _RESUME_PROBE)
        self.assertIn(r"/\.(pdf|docx?)\b/i", _RESUME_PROBE)
        self.assertNotIn(r"/\\.(pdf|docx?)\\b/i", _RESUME_PROBE)
        self.assertIn("...(inlineWizard ? [inlineWizard] : [])", _RESUME_PROBE)
        self.assertNotIn("document.body.innerText", _RESUME_PROBE)
        if shutil.which("node"):
            script = subprocess.run(
                ["node", "--check"], input=_RESUME_PROBE, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                check=False,
            )
            self.assertEqual(script.returncode, 0, script.stderr)

    def test_dom_probe_uses_selected_controls_and_never_full_body_text(self):
        self.assertIn('input[type="radio"]:checked', _RESUME_PROBE)
        self.assertIn('[aria-selected="true"]', _RESUME_PROBE)
        self.assertNotIn("document.body.innerText", _RESUME_PROBE)
        self.assertIn("input[type=\"file\"]", _RESUME_PROBE)


class ResumeSubmissionGateTests(unittest.TestCase):
    def run_flow(self, state):
        page = SimpleNamespace(url="https://www.linkedin.com/jobs/view/4461542106/")
        def action(_page, texts):
            if "Review" in texts:
                return None, ""
            return object(), "Submit application"

        with patch("application_flow.build_page_fill_plan",
                   return_value=FillPlan(can_fill=True)), \
             patch("application_flow.apply_fill_plan", return_value=()), \
             patch("application_flow.inspect_resume_evidence", return_value=state), \
             patch("application_flow.inspect_easy_apply_state"), \
             patch("application_flow._blocking_confirmation_dialog", return_value=""), \
             patch("application_flow._visible_action", side_effect=action), \
             patch("application_flow.trace_event") as tracer:
            result = run_safe_application_flow(
                page, {}, resume_path="/fake/resume.docx",
                live_submission_enabled=True, advance=True
            )
        return result, tracer

    def test_missing_attachment_evidence_blocks_submit(self):
        for state in ("attachment_unverified", "file_input_selected_unconfirmed",
                      "different_resume_selected"):
            with self.subTest(state=state):
                result, _ = self.run_flow(state)
                self.assertEqual(result.state, "BLOCKED_RESUME_UNVERIFIED")
                self.assertNotEqual(result.state, "SUBMIT_READY")

    def test_matching_selected_resume_allows_ready_state(self):
        result, trace = self.run_flow("matching_resume_selected")
        self.assertEqual(result.state, "SUBMIT_READY")
        names = [call.args[0] for call in trace.call_args_list]
        self.assertIn("resume_attachment_inspection", names)


if __name__ == "__main__":
    unittest.main()
