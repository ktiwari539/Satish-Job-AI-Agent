"""Scheduling regression checks use no accounts, browser or network."""
import contextlib
import io
import json
import os
import plistlib
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from scheduled_review import build_review_command, acquire_run_lock, main, ReviewConfigurationError


class ScheduledReviewTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.sources = self.root/'employer sources.json'
        self.sources.write_text(json.dumps(dict(greenhouse_boards=['fixture'], lever_sites=['fixture'])))
        self.env = dict(JOB_AGENT_SOURCES=str(self.sources))

    @contextlib.contextmanager
    def working_directory(self):
        previous = Path.cwd()
        os.chdir(self.root)
        try:
            yield
        finally:
            os.chdir(previous)

    def test_scheduled_command_prepares_with_live_controls_and_cannot_submit(self):
        command = build_review_command(self.env)
        self.assertEqual(command[:2], [sys.executable, 'src/certify_portals.py'])
        self.assertIn('--use-control-sheet', command)
        self.assertIn('--no-login', command)
        self.assertEqual(command[command.index('--otp-mode')+1], 'none')
        self.assertFalse(any('approve' in arg or 'live-application' in arg for arg in command))

    def test_browser_portals_cannot_be_silently_enabled_by_environment(self):
        for portal in ('linkedin', 'indeed', 'naukri', 'instahyre', 'all', ''):
            with self.subTest(portal=portal), self.assertRaisesRegex(ReviewConfigurationError, 'manual_or_authorized'):
                build_review_command(dict(self.env, JOB_AGENT_PORTALS=portal))

    def test_empty_or_invalid_employer_configuration_stops_before_worker(self):
        for value in ({}, [], {'greenhouse_boards': [], 'lever_sites': []},
                      {'greenhouse_boards': ['fixture'], 'lever_sites': ['']}):
            self.sources.write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaisesRegex(ReviewConfigurationError, 'sources_configuration'):
                build_review_command(self.env)

    def test_one_configured_feed_does_not_require_another_provider(self):
        self.sources.write_text(json.dumps(dict(lever_sites=['fixture'])))
        command = build_review_command(dict(self.env, JOB_AGENT_PORTALS='lever,lever'))
        self.assertEqual(command[command.index('--portals')+1], 'lever')

    def test_bound_and_preserve_user_search_arguments_without_shell_evaluation(self):
        query = 'Customer Success Manager; $(not-a-command)'
        command = build_review_command(dict(self.env, JOB_AGENT_QUERY=query, JOB_AGENT_MAX_JOBS='20'))
        self.assertEqual(command[command.index('--query')+1], query)
        self.assertEqual(command[command.index('--sources')+1], str(self.sources))
        for maximum in ('0', '21', '80', 'many'):
            with self.subTest(maximum=maximum), self.assertRaisesRegex(ReviewConfigurationError, 'max_jobs_invalid'):
                build_review_command(dict(self.env, JOB_AGENT_MAX_JOBS=maximum))

    def test_lock_survives_worker_exec_and_recovers_after_forced_termination(self):
        lock = self.root/'worker.lock'
        worker = "import signal; print('ready', flush=True); signal.pause()"
        launcher = ('import os, sys; sys.path.insert(0, sys.argv[1]); '
            'from scheduled_review import acquire_run_lock; '
            'fd=acquire_run_lock(sys.argv[2]); '
            'os.execv(sys.executable, [sys.executable, "-c", sys.argv[3]])')
        process = subprocess.Popen([sys.executable, '-c', launcher, str(ROOT/'src'), str(lock), worker],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(select.select([process.stdout], [], [], 5)[0], 'worker did not start')
            self.assertEqual(process.stdout.readline().strip(), 'ready')
            self.assertIsNone(acquire_run_lock(lock))
        finally:
            process.kill()
            process.communicate(timeout=5)
        self.assertTrue(lock.is_file())
        descriptor = acquire_run_lock(lock)
        self.assertIsNotNone(descriptor)
        os.close(descriptor)

    def test_configuration_block_reports_zero_submissions_without_exec(self):
        with self.working_directory(), patch.dict(os.environ, {'JOB_AGENT_PORTALS': 'linkedin'}, clear=True), \
                patch('scheduled_review.os.execv') as execute, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(), 2)
            execute.assert_not_called()
            result = json.loads(output.getvalue())
            self.assertEqual(result['status'], 'scheduled_review_configuration_required')
            self.assertEqual(result['submitted'], 0)
            self.assertFalse(result['submission_enabled'])
            self.assertEqual(json.loads(Path('data/certification/scheduled-review-launch.json').read_text()), result)

    def test_overlapping_launch_does_not_overwrite_active_launch_evidence(self):
        with self.working_directory():
            descriptor = acquire_run_lock('data/review-worker.lock')
            try:
                with patch('scheduled_review.emit_status') as emit, contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(), 0)
                    emit.assert_not_called()
                    self.assertEqual(json.loads(output.getvalue())['status'], 'scheduled_review_already_running')
            finally:
                os.close(descriptor)

    def test_review_wrapper_reuses_virtualenv_and_preserves_explicit_interpreter(self):
        (self.root/'scripts').mkdir()
        shutil.copy2(ROOT/'scripts/run_review_window.sh', self.root/'scripts/run_review_window.sh')
        python = self.root/'.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.write_text('#!'+sys.executable+'\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        python.chmod(0o755)
        env = dict(os.environ, JOB_AGENT_REPO=str(self.root))
        env.pop('JOB_AGENT_PYTHON', None)
        for override in (None, self.root/'custom python'):
            if override:
                shutil.copy2(python, override)
                env['JOB_AGENT_PYTHON'] = str(override)
                python.write_text('#!/bin/bash\nexit 99\n')
            result = subprocess.run(['bash', str(self.root/'scripts/run_review_window.sh')],
                env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), ['src/scheduled_review.py'])

    def test_installer_serializes_paths_and_only_allowlisted_settings_without_installing(self):
        source = (ROOT/'scripts/install_launchd_schedule.sh').read_text()
        program = source.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        target = self.root/'review.plist'
        repo = self.root/'Mac & work <project>'
        env = dict(os.environ, JOB_AGENT_QUERY='Customer Success & Support', JOB_AGENT_PORTALS='lever',
            JOB_AGENT_SOURCES='data/employer sources.json', PASSWORD='fixture-never-export')
        result = subprocess.run([sys.executable, '-c', program, str(target),
            str(repo/'scripts/run_review_window.sh'), str(repo), str(repo/'data')],
            env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = plistlib.loads(target.read_bytes())
        self.assertEqual(payload['ProgramArguments'][1], str(repo/'scripts/run_review_window.sh'))
        self.assertEqual(payload['EnvironmentVariables']['JOB_AGENT_REPO'], str(repo))
        self.assertEqual(payload['EnvironmentVariables']['JOB_AGENT_QUERY'], env['JOB_AGENT_QUERY'])
        self.assertEqual(payload['EnvironmentVariables']['JOB_AGENT_PYTHON'], sys.executable)
        self.assertNotIn('PASSWORD', payload['EnvironmentVariables'])
