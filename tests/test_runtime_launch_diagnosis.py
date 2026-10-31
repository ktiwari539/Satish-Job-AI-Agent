import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from browser_runtime import _launch_failure, runtime_metadata, check_browser_runtime, BrowserRuntimeUnavailable, PlaywrightSession, _probe_clean_browser


class LaunchDiagnosisTests(unittest.TestCase):
    def test_failed_launch_has_safe_signals_without_raw_browser_log(self):
        exc = RuntimeError('Target page, context or browser has been closed. [pid=123] process did exit: exitCode=11, signal=SIGTRAP private@example.invalid /Users/private/browser-profile')
        result = _launch_failure(exc, details={'playwright_version':'1.55.0'}).diagnostics()
        self.assertEqual(result['runtime']['browser_exit_code'], 11)
        self.assertEqual(result['runtime']['browser_exit_signal'], 'SIGTRAP')
        self.assertTrue(result['runtime']['launch_signals']['target_closed'])
        self.assertNotIn('private', json.dumps(result))

    def test_known_failures_have_distinct_actions(self):
        cases = {
            "Executable doesn't exist":'chromium_not_installed',
            'ProcessSingleton lock':'browser_profile_in_use',
            'profile was created by a newer version':'browser_profile_version_newer',
            'bad CPU type in executable':'browser_architecture_mismatch',
            'EACCES Permission denied':'browser_profile_permission_denied',
            'Library not loaded':'browser_os_dependency_missing',
            'Timeout 15000ms exceeded':'browser_launch_timeout',
        }
        for message, code in cases.items():
            with self.subTest(code=code):
                self.assertEqual(_launch_failure(RuntimeError(message)).reason_code, code)

    def test_version_probe_reads_only_bounded_version_marker(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'Last Version'
            p.write_text('140.0.7339.16')
            self.assertEqual(runtime_metadata(root)['profile_browser_version'], '140.0.7339.16')
            p.write_text('private@example.invalid')
            self.assertNotIn('profile_browser_version', runtime_metadata(root))

    def test_older_browser_never_opens_a_newer_saved_profile(self):
        factory = MagicMock()
        info=dict(playwright_version='1.55.0',chromium_version='140.0.1.0',profile_browser_version='146.0.1.0')
        with tempfile.TemporaryDirectory() as root, \
             patch('browser_runtime._load_sync_playwright', return_value=factory), \
             patch('browser_runtime.runtime_metadata', return_value=info):
            with self.assertRaises(BrowserRuntimeUnavailable) as error:
                PlaywrightSession(SimpleNamespace(user_data_dir=root)).__enter__()
        self.assertEqual(error.exception.reason_code, 'browser_profile_version_newer')
        factory.assert_not_called()

    def test_outdated_playwright_is_reported_before_driver_start(self):
        with patch('browser_runtime._load_sync_playwright'), patch('browser_runtime.runtime_metadata', return_value=dict(playwright_version='1.51.0')):
            with self.assertRaises(BrowserRuntimeUnavailable) as error:
                check_browser_runtime()
        self.assertEqual(error.exception.reason_code, 'playwright_outdated')

    def test_unknown_saved_profile_failure_runs_one_clean_blank_probe(self):
        factory, driver = MagicMock(), MagicMock()
        factory.return_value.start.return_value=driver
        driver.chromium.launch_persistent_context.side_effect=RuntimeError('Target page, context or browser has been closed')
        with tempfile.TemporaryDirectory() as root, \
             patch('browser_runtime._load_sync_playwright', return_value=factory), \
             patch('browser_runtime._probe_clean_browser', return_value={'clean_profile_launch':'passed'}) as probe:
            with self.assertRaises(BrowserRuntimeUnavailable) as error:
                PlaywrightSession(SimpleNamespace(user_data_dir=root,headless=False,slow_mo_ms=0)).__enter__()
        probe.assert_called_once_with(headless=False)
        self.assertEqual(error.exception.diagnostics()['next_action'], 'inspect_saved_profile_launch_without_resetting_it')
        driver.chromium.launch_persistent_context.assert_called_once()
        self.assertEqual(driver.chromium.launch_persistent_context.call_args.kwargs['timeout'], 15000)

    def test_blank_probe_has_no_saved_profile_or_portal_navigation(self):
        factory, driver = MagicMock(), MagicMock()
        factory.return_value.start.return_value=driver
        with patch('browser_runtime._load_sync_playwright', return_value=factory):
            self.assertEqual(_probe_clean_browser(headless=True), {'clean_profile_launch':'passed'})
        driver.chromium.launch.assert_called_once_with(headless=True,timeout=8000)
        driver.chromium.launch_persistent_context.assert_not_called()
        driver.stop.assert_called_once()
