"""Safe reconciliation of an uncertain live Submit without reapplying."""
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
from linkedin_applied_status import inspect_exact_applied_status
from linkedin_exact_job import parse_linkedin_target

URL = "https://www.linkedin.com/jobs/view/4461542106/"
TARGET = parse_linkedin_target(URL)


class AppliedStatusTests(unittest.TestCase):
    def test_proven_applied_control_returns_positive_evidence_not_confirmation_count(self):
        page = SimpleNamespace(url=URL, evaluate=lambda script: {
            "applied": True, "evidence": "exact_job_applied_control"
        })
        result = inspect_exact_applied_status(page, TARGET)
        self.assertEqual(result["status"], "linkedin_exact_job_applied_visible")
        self.assertEqual(result["evidence_kind"], "exact_job_applied_control")

    def test_application_submitted_status_section_is_exact_job_evidence(self):
        page = SimpleNamespace(url=URL, evaluate=lambda script: {
            "applied": True, "evidence": "exact_job_application_status"
        })
        result = inspect_exact_applied_status(page, TARGET)
        self.assertEqual(result["status"], "linkedin_exact_job_applied_visible")
        self.assertEqual(result["evidence_kind"], "exact_job_application_status")

    def test_status_probe_requires_scoped_visible_section_not_body_text(self):
        from linkedin_applied_status import _APPLIED_PROBE
        self.assertIn("statusLabels", _APPLIED_PROBE)
        self.assertIn("sectionText.length > 320", _APPLIED_PROBE)
        self.assertNotIn("document.body.innerText", _APPLIED_PROBE)

    def test_absent_applied_does_not_mean_not_applied(self):
        page = SimpleNamespace(url=URL, evaluate=lambda script: {
            "applied": False, "evidence": ""
        })
        result = inspect_exact_applied_status(page, TARGET)
        self.assertEqual(result["status"], "application_status_unverified")

    def test_untrusted_script_evidence_does_not_prove_applied(self):
        page = SimpleNamespace(url=URL, evaluate=lambda script: {
            "applied": True, "evidence": "unknown_marker"
        })
        result = inspect_exact_applied_status(page, TARGET)
        self.assertEqual(result["status"], "application_status_unverified")

    def test_different_job_id_rejected_before_or_after_probe(self):
        page = SimpleNamespace(url="https://www.linkedin.com/jobs/view/4476701830/",
                               evaluate=lambda script: {"applied": True, "evidence": "exact_job_applied_control"})
        with self.assertRaisesRegex(ValueError, "exact_job_navigation_id_mismatch"):
            inspect_exact_applied_status(page, TARGET)

    def test_cli_status_check_never_invokes_application_engine_or_store(self):
        page = SimpleNamespace(url=URL, wait_for_timeout=lambda n: None)
        runtime = MagicMock()
        runtime.page = page
        runtime.__enter__.return_value = runtime
        session = SimpleNamespace(authenticated=True, needs_human_action=False)
        args = SimpleNamespace(
            portal="linkedin", job_url=URL,
            approve_one_live_application=False, profile_dir="browser-profile",
            headless=True, db="data/jobs.db",
        )
        with patch("job_agent_cli.PlaywrightSession", return_value=runtime), \
             patch("job_agent_cli.LinkedInBrowserAdapter") as adapter, \
             patch("job_agent_cli.bounded_goto"), \
             patch("job_agent_cli.ensure_exact_target"), \
             patch("job_agent_cli.inspect_exact_applied_status",
                   return_value={"status":"linkedin_exact_job_applied_visible",
                                 "evidence_kind":"exact_job_applied_control"}), \
             patch("job_agent_cli.JobStore") as store, \
             patch("job_agent_cli.run_linkedin_application") as apply, \
             patch("job_agent_cli.trace_event"), \
             redirect_stdout(io.StringIO()) as out:
            adapter.return_value.login_state.return_value = session
            code = job_agent_cli._check_linkedin_applied_status(args)
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["confirmed"], 0)
        self.assertEqual(result["attempted"], 0)
        self.assertTrue(result["no_submission_actions"])
        self.assertFalse(result["db_modified"])
        apply.assert_not_called()
        store.assert_not_called()

    def test_cannot_mix_status_check_with_live_approval(self):
        args = SimpleNamespace(
            portal="linkedin", job_url=URL,
            approve_one_live_application=True,
        )
        with patch("job_agent_cli.PlaywrightSession") as browser, \
             redirect_stdout(io.StringIO()) as out:
            code = job_agent_cli._check_linkedin_applied_status(args)
        self.assertEqual(code, 2)
        browser.assert_not_called()
        self.assertEqual(json.loads(out.getvalue())["attempted"], 0)

    def test_profile_city_is_read_only_and_separate_from_search_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "private_profile.json"
            p.write_text(json.dumps({"location":"Mumbai", "email":"private@example.com"}))
            args = SimpleNamespace(private_profile=str(p), location="India")
            with redirect_stdout(io.StringIO()) as out:
                code = job_agent_cli._check_local_profile_city(args)
            self.assertEqual(code, 0)
            result = json.loads(out.getvalue())
            self.assertEqual(result["applicant_city"], "Mumbai")
            self.assertTrue(result["search_location_is_separate"])
            self.assertNotIn("private@example.com", out.getvalue())


if __name__ == "__main__":
    unittest.main()
