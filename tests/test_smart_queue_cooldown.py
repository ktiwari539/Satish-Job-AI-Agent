"""Persistent cooldown prevents repeating the same failed LinkedIn QA job."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from smart_queue_history import read_history, record_check, skip_reason
from smart_debug_queue import debug_easy_apply_queue
from test_smart_debug_queue import args, job


class SmartQueueCooldownTests(unittest.TestCase):
    def test_history_prevents_immediate_retry(self):
        with tempfile.TemporaryDirectory() as root:
            db=str(Path(root)/"jobs.db")
            record_check(db, "4482859467", "easy_apply_debug_review_unverified", "REVIEW_INSPECTED")
            self.assertEqual(skip_reason(read_history(db), "4482859467"), "recently_checked")

    def test_queue_skips_recent_job_and_checks_next(self):
        with tempfile.TemporaryDirectory() as root:
            db=str(Path(root)/"jobs.db")
            record_check(db, "4482859467", "easy_apply_debug_blocked", "BLOCKED_AFTER_FILL")
            runtime=MagicMock()
            adapter=MagicMock()
            adapter.login_state.return_value=MagicMock(authenticated=True,needs_human_action=False)
            adapter.extract_search_results.return_value=[job(4482859467),job(4482859468)]
            def run(a):
                print(json.dumps({"status":"easy_apply_debug_blocked","flow_state":"BLOCKED_AFTER_FILL","flow_tested":True}))
                return 4
            with patch("smart_debug_queue.PlaywrightSession",return_value=runtime), \
                 patch("smart_debug_queue.LinkedInBrowserAdapter",return_value=adapter), \
                 patch("smart_debug_queue.debug_easy_apply",side_effect=run) as debug, \
                 patch("smart_debug_queue.trace_event"), redirect_stdout(io.StringIO()) as output:
                code=debug_easy_apply_queue(args(db=db,job_url="",smart_max_forms=1))
            self.assertEqual(code,4)
            self.assertEqual(debug.call_count,1)
            self.assertEqual(debug.call_args.args[0].job_url,job(4482859468).url)
            self.assertEqual(json.loads(output.getvalue().splitlines()[-1])["skipped"]["cooldown"],1)
            self.assertEqual(skip_reason(read_history(db),"4482859468"),"recently_checked")


if __name__=="__main__":
    unittest.main()
