"""Launch/setup must stay in the chosen environment and preserve private state."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/certify_linkedin.sh'


class CertificationLauncherTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root/'scripts').mkdir()
        shutil.copy2(SOURCE, self.root/'scripts/certify_linkedin.sh')
        self.python = self.root/'.venv/bin/python'
        self.python.parent.mkdir(parents=True)
        self.python.write_text('#!'+sys.executable+'\n'
            'import json, os, sys\n'
            'with open(os.environ["LAUNCH_LOG"], "a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
            'if sys.argv[1:2] == ["-c"]: sys.exit(int(os.environ.get("IMPORT_EXIT", "0")))\n')
        self.python.chmod(0o755)
        self.log = self.root/'launch.jsonl'
        self.env = dict(os.environ, LAUNCH_LOG=str(self.log))
        self.env.pop('JOB_AGENT_PYTHON', None)
        self.marker = self.root/'browser-profile/private-marker'
        self.marker.parent.mkdir()
        self.marker.write_text('preserve me')

    def invoke(self, *args):
        r = subprocess.run(['bash', str(self.root/'scripts/certify_linkedin.sh'), *args],
            env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.marker.read_text(), 'preserve me')
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_setup_preserves_working_playwright_and_forwards_args_exactly(self):
        calls = self.invoke('--setup', '--include-issue3-jobs', '--rounds', '3', '--db', 'path with spaces/jobs.db')
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1], ['-m', 'playwright', 'install', 'chromium'])
        self.assertEqual(calls[2], ['src/certify_linkedin.py', '--include-issue3-jobs', '--rounds', '3', '--db', 'path with spaces/jobs.db'])
        self.assertFalse(any('pip' in call for call in calls))

    def test_missing_import_installs_in_same_project_python(self):
        self.env['IMPORT_EXIT'] = '1'
        calls = self.invoke('--setup', '--rounds', '0')
        self.assertEqual(calls[1], ['-m', 'pip', 'install', '-r', 'tests/browser/requirements.txt'])
        self.assertEqual(calls[2], ['-m', 'playwright', 'install', 'chromium'])
        self.assertEqual(calls[-1], ['src/certify_linkedin.py', '--rounds', '0'])

    def test_normal_run_does_not_install_or_modify_environment(self):
        calls = self.invoke('--include-issue3-jobs')
        self.assertEqual(calls, [['src/certify_linkedin.py', '--include-issue3-jobs']])

    def test_explicit_interpreter_override_is_respected(self):
        override = self.root/'custom python'
        shutil.copy2(self.python, override)
        self.python.write_text('#!/bin/bash\nexit 99\n')
        self.env['JOB_AGENT_PYTHON'] = str(override)
        self.assertEqual(self.invoke('--rounds', '0'), [['src/certify_linkedin.py', '--rounds', '0']])
