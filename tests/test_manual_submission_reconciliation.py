"""Manual submission reconciliation never opens the browser or submits again."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from job_agent_cli import _run
from store import JobStore
from models import Job

class ManualSubmissionReconciliationTests(unittest.TestCase):
    def test_record_confirmed_manual_job_and_prevent_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "jobs.db")
            args = SimpleNamespace(db=db,
                record_manual_applied_job="https://www.linkedin.com/jobs/view/4482859467/",
                approve_one_live_application=False,debug_easy_apply_only=False)
            with patch("job_agent_cli.PlaywrightSession") as browser, redirect_stdout(io.StringIO()) as output:
                code = _run(args)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "manual_application_recorded")
            browser.assert_not_called()
            job=Job(source="linkedin",external_id="4482859467",company="GobbleCube",
                    title="Customer Success Manager",location="India",
                    url="https://www.linkedin.com/jobs/view/4482859467/",description="")
            self.assertTrue(JobStore(db).is_applied(job))
    def test_manual_record_rejects_wrong_domain(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=SimpleNamespace(db=str(Path(tmp)/"jobs.db"),
                record_manual_applied_job="https://invalid.example/jobs/view/4482859467/",
                approve_one_live_application=False,debug_easy_apply_only=False)
            with redirect_stdout(io.StringIO()) as out:
                code=_run(args)
            self.assertEqual(code,4)
            self.assertEqual(json.loads(out.getvalue())["status"],"manual_record_failed")

if __name__=="__main__":
    unittest.main()
