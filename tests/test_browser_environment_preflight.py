"""Environment failures are not six job failures or legitimate cooldowns."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from browser_runtime import BrowserRuntimeUnavailable, PlaywrightSession, check_browser_runtime
from certify_linkedin import run, summarize
from smart_queue_history import read_history, record_check, skip_reason
from smart_debug_queue import debug_easy_apply_queue
from test_smart_debug_queue import args as queue_args, job


class BrowserEnvironmentPreflightTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = str(Path(self.folder.name) / 'jobs.db')
        self.args = SimpleNamespace(job_url=[], include_issue3_jobs=True, rounds=3,
            db=self.db, report=str(Path(self.folder.name)/'report.json'))

    def test_missing_playwright_is_reported_once_before_any_job_or_history(self):
        with patch('browser_runtime._load_sync_playwright', side_effect=ImportError('private interpreter path')), \
             patch('certify_linkedin.debug_easy_apply') as debug, \
             patch('certify_linkedin.debug_easy_apply_queue') as queue, \
             patch('certify_linkedin.record_check') as history, redirect_stdout(io.StringIO()) as output:
            code = run(self.args)
        report = json.loads(Path(self.args.report).read_text())
        self.assertEqual(code, 2)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertEqual(report['environment_blocker']['reason_code'], 'playwright_import_failed')
        self.assertEqual(report['distinct_jobs_checked'], 0)
        self.assertEqual(report['results'], [])
        self.assertNotIn('private interpreter path', output.getvalue())
        for mock in (debug, queue, history):
            mock.assert_not_called()

    def test_launch_runtime_failure_stops_after_first_candidate(self):
        def fail(args):
            print(json.dumps(dict(status='browser_runtime_unavailable', reason_code='chromium_not_installed')))
            return 2
        with patch('certify_linkedin.check_browser_runtime'), \
             patch('certify_linkedin.debug_easy_apply', side_effect=fail) as debug, \
             patch('certify_linkedin.debug_easy_apply_queue') as queue, redirect_stdout(io.StringIO()):
            self.assertEqual(run(self.args), 2)
        self.assertEqual(debug.call_count, 1)
        queue.assert_not_called()
        self.assertEqual(read_history(self.db), {})
        report = json.loads(Path(self.args.report).read_text())
        self.assertEqual(report['distinct_jobs_checked'], 0)
        self.assertEqual(report['distinct_jobs_considered'], 1)

    def test_queue_setup_failure_keeps_actionable_details(self):
        self.args.include_issue3_jobs = False
        def unavailable(args):
            print(json.dumps(dict(status='smart_queue_browser_unavailable', reason_code='chromium_not_installed', next_action='install_chromium_with_the_same_python_interpreter')))
            return 4
        with patch('certify_linkedin.check_browser_runtime'), \
             patch('certify_linkedin.debug_easy_apply_queue', side_effect=unavailable) as queue, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(run(self.args), 2)
        self.assertEqual(queue.call_count, 1)
        report = json.loads(Path(self.args.report).read_text())
        self.assertEqual(report['queue_rounds'][0]['reason_code'], 'chromium_not_installed')
        self.assertEqual(report['environment_blocker']['next_action'], 'install_chromium_with_the_same_python_interpreter')
        self.assertIn('smart_queue_browser_unavailable', output.getvalue())

    def test_old_missing_runtime_entries_do_not_impose_cooldown(self):
        history = {'4455142560': dict(status='browser_runtime_unavailable', checked_at='2026-10-26T15:00:00+00:00')}
        self.assertEqual(skip_reason(history, '4455142560'), '')
        record_check(self.db, '4455142560', 'browser_runtime_unavailable', '')
        self.assertEqual(read_history(self.db), {})

    def test_environment_failure_does_not_overwrite_applied_protection(self):
        record_check(self.db, '4455142560', 'debug_portal_already_applied_skipped', 'NOT_RUN', entry_classification='ALREADY_APPLIED')
        record_check(self.db, '4455142560', 'browser_runtime_unavailable', '')
        self.assertEqual(skip_reason(read_history(self.db), '4455142560'), 'already_applied')

    def test_six_unopened_jobs_are_not_six_checked_jobs(self):
        report = summarize([dict(job_id=str(i), status='browser_runtime_unavailable') for i in range(6)])
        self.assertEqual(report['distinct_jobs_considered'], 6)
        self.assertEqual(report['distinct_jobs_checked'], 0)
        self.assertFalse(report['acceptance_passed'])

    def test_failed_context_launch_stops_driver_and_reports_missing_browser(self):
        driver = MagicMock()
        driver.chromium.launch_persistent_context.side_effect = RuntimeError("Executable doesn't exist at private-path")
        factory = MagicMock()
        factory.return_value.start.return_value = driver
        with patch('browser_runtime._load_sync_playwright', return_value=factory):
            with self.assertRaises(BrowserRuntimeUnavailable) as failure:
                PlaywrightSession(SimpleNamespace(user_data_dir=self.folder.name, headless=True, slow_mo_ms=0)).__enter__()
        self.assertEqual(failure.exception.reason_code, 'chromium_not_installed')
        driver.stop.assert_called_once()
        self.assertNotIn('private-path', json.dumps(failure.exception.diagnostics()))

    def test_locked_profile_is_not_deleted_or_retried(self):
        driver = MagicMock()
        driver.chromium.launch_persistent_context.side_effect = RuntimeError('ProcessSingleton private-profile')
        factory = MagicMock()
        factory.return_value.start.return_value = driver
        with patch('browser_runtime._load_sync_playwright', return_value=factory):
            with self.assertRaises(BrowserRuntimeUnavailable) as failure:
                PlaywrightSession(SimpleNamespace(user_data_dir=self.folder.name, headless=True, slow_mo_ms=0)).__enter__()
        self.assertEqual(failure.exception.reason_code, 'browser_profile_in_use')
        driver.chromium.launch_persistent_context.assert_called_once()
        self.assertTrue(Path(self.folder.name).is_dir())

    def test_queue_stops_on_global_failure_without_recording_or_retrying_other_jobs(self):
        runtime, adapter = MagicMock(), MagicMock()
        adapter.login_state.return_value = SimpleNamespace(authenticated=True, needs_human_action=False)
        adapter.extract_search_results.return_value = [job(9000000001), job(9000000002)]
        def unavailable(args):
            print(json.dumps(dict(status='browser_runtime_unavailable', reason_code='browser_profile_in_use',
                                  next_action='close_the_agent_browser_then_retry_without_deleting_profile')))
            return 2
        with patch('smart_debug_queue.PlaywrightSession', return_value=runtime), \
             patch('smart_debug_queue.LinkedInBrowserAdapter', return_value=adapter), \
             patch('smart_debug_queue.debug_easy_apply', side_effect=unavailable) as debug, redirect_stdout(io.StringIO()) as output:
            code = debug_easy_apply_queue(queue_args(db=self.db, job_url=''))
        self.assertEqual(code, 4)
        self.assertEqual(debug.call_count, 1)
        report = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(report['reason_code'], 'browser_profile_in_use')
        self.assertEqual(report['forms_checked'], 0)
        self.assertEqual(read_history(self.db), {})


if __name__ == '__main__':
    unittest.main()
