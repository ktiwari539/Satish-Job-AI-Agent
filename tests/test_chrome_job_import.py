import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from chrome_job_import import evaluate_capture, validate_capture, main
from models import CandidateProfile
from portal_export_urls import canonical_export_job_url
from profile_consistency import ProfileFactsConflict
from sheet_control import ControlBundle

PUBLIC = dict(target_roles=['customer success manager'], skills=['customer success', 'sla', 'stakeholder management', 'onboarding'],
              skill_taxonomy=['customer success', 'sla', 'stakeholder management', 'onboarding'], preferred_locations=['india'],
              remote_allowed=True, total_experience_years=8, india_authorized=True)
PRIVATE = dict(full_name='Fixture Applicant', email='fixture@example.invalid', phone='9999999999', experience_years=8)
PROFILE = CandidateProfile.from_dict(PUBLIC)
POLICY = SimpleNamespace(threshold=75, duplicate_cooldown_days=90)
NOW = datetime(2026, 10, 28, 8, tzinfo=timezone.utc)
URL = 'https://in.indeed.com/viewjob?jk=0123456789abcdef'
JD = 'Customer success manager in Bengaluru India: customer success SLA stakeholder management onboarding. ' * 4


def capture(portal='indeed'):
    return dict(schema_version=1, portal=portal, captured_at=NOW.isoformat(), page_kind='detail', jobs=[dict(
        title='Customer Success Manager', company='Fixture Company', location='Bengaluru, India', description=JD,
        url=URL if portal == 'indeed' else 'https://www.naukri.com/job-listings-fixture-123', capture_kind='detail')])


def ledger(duplicate=False):
    store = Mock()
    store.is_recent_similar_application.return_value = duplicate
    return store


class ChromeJobImportTests(unittest.TestCase):
    def test_both_portals_score_review_only_without_browser_or_submission(self):
        for portal in ('naukri', 'indeed'):
            with self.subTest(portal=portal):
                store = ledger()
                result = evaluate_capture(capture(portal), PROFILE, PRIVATE, POLICY, store, now=NOW)
                self.assertEqual(result['qualified'], 1)
                self.assertEqual(result['portal'], portal)
                self.assertFalse(result['application_ready'])
                self.assertFalse(result['submission_enabled'])
                self.assertEqual(result['submitted'], 0)
                self.assertEqual([call[0] for call in store.mock_calls], ['is_recent_similar_application'])

    def test_distinct_indeed_ids_and_tracking_variants_preserve_identity(self):
        data = capture()
        data['jobs'].append({**data['jobs'][0], 'url': URL + '&tracking=private-token'})
        data['jobs'].append({**data['jobs'][0], 'url': URL.replace('0123456789abcdef', 'fedcba9876543210')})
        original = copy.deepcopy(data)
        result = evaluate_capture(data, PROFILE, PRIVATE, POLICY, ledger(), now=NOW)
        self.assertEqual(result['discovered'], 2)
        self.assertNotEqual(result['jobs'][0]['url'], result['jobs'][1]['url'])
        self.assertNotIn('private-token', json.dumps(result))
        self.assertEqual(data, original)

    def test_unsafe_ambiguous_or_account_urls_are_rejected(self):
        for url in ('http://in.indeed.com/viewjob?jk=0123456789abcdef', 'https://indeed.com.evil.invalid/viewjob?jk=0123456789abcdef',
                    'https://user@in.indeed.com/viewjob?jk=0123456789abcdef', 'https://in.indeed.com:444/viewjob?jk=0123456789abcdef',
                    URL + '&jk=0123456789abcdef', URL + '&vjk=fedcba9876543210', URL.replace('0123456789abcdef', 'short'),
                    'https://secure.indeed.com/viewjob?jk=0123456789abcdef', 'https://in.indeed.com/account/login?jk=0123456789abcdef'):
            with self.subTest(url=url):
                self.assertEqual(canonical_export_job_url('indeed', url), '')
        self.assertEqual(canonical_export_job_url('naukri', 'https://www.naukri.com/mnjuser/profile'), '')

    def test_selected_search_id_is_canonicalized_without_tracking(self):
        self.assertEqual(canonical_export_job_url('indeed', 'https://in.indeed.com/jobs?q=manager&vjk=0123456789abcdef#private'), URL)

    def test_stale_future_and_naive_capture_timestamps_are_rejected(self):
        for timestamp in ((NOW - timedelta(days=2)).isoformat(), (NOW + timedelta(minutes=3)).isoformat(),
                          NOW.replace(tzinfo=None).isoformat(), 'unverified'):
            data = capture()
            data['captured_at'] = timestamp
            with self.assertRaisesRegex(ValueError, 'capture_timestamp'):
                validate_capture(data, now=NOW)

    def test_search_snippets_and_short_jds_are_never_qualified(self):
        for kind, description in (('search', JD), ('detail', 'Apply here')):
            data = capture()
            data['page_kind'] = data['jobs'][0]['capture_kind'] = kind
            data['jobs'][0]['description'] = description
            result = evaluate_capture(data, PROFILE, PRIVATE, POLICY, ledger(), now=NOW)
            self.assertEqual(result['qualified'], 0)
            self.assertEqual(result['needing_full_jd'], 1)

    def test_existing_application_is_excluded_without_ledger_writes(self):
        result = evaluate_capture(capture(), PROFILE, PRIVATE, POLICY, ledger(True), now=NOW)
        self.assertEqual(result['jobs'][0]['status'], 'SKIPPED_RECENT_APPLICATION')
        self.assertEqual(result['qualified'], 0)

    def test_inspection_must_correlate_to_exact_exported_job(self):
        data = capture()
        data['application_inspection'] = dict(schema_version=2, portal='indeed', mode='READ_ONLY_INSPECTION',
            job_url=URL.replace('0123456789abcdef', 'fedcba9876543210'), application_controls=['submit'],
            captcha_present=False, otp_present=False, account_login_present=False)
        with self.assertRaisesRegex(ValueError, 'inspection_job_identity_mismatch'):
            validate_capture(data, now=NOW)

    def test_inspection_never_exports_unknown_values_or_implies_release_readiness(self):
        data = capture()
        data['application_inspection'] = dict(schema_version=2, portal='indeed', mode='READ_ONLY_INSPECTION', job_url=URL,
            application_controls=['apply'], captcha_present=False, otp_present=False, account_login_present=False,
            entered_email='PRIVATE-VALUE', cookie='PRIVATE-COOKIE')
        result = evaluate_capture(data, PROFILE, PRIVATE, POLICY, ledger(), now=NOW)
        self.assertNotIn('PRIVATE-', json.dumps(result))
        self.assertFalse(result['application_inspection']['application_ready'])

    def test_conflicting_private_profile_stops_qualification(self):
        with self.assertRaises(ProfileFactsConflict):
            evaluate_capture(capture(), PROFILE, {**PRIVATE, 'experience_years': '3'}, POLICY, ledger(), now=NOW)

    def test_cli_preserves_sheet_pause_before_capture_read_or_ledger_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public, private = root / 'profile.json', root / 'private.json'
            public.write_text(json.dumps(PUBLIC)); private.write_text(json.dumps(PRIVATE))
            bundle = ControlBundle(dict(agent_enabled=False, operating_mode='VALIDATION'), ())
            argv = ['chrome_job_import.py', '--file', str(root / 'does-not-exist.json'), '--profile', str(public),
                    '--private-profile', str(private), '--report', str(root / 'report.json')]
            with patch.object(sys, 'argv', argv), patch('chrome_job_import.load_requested_control', return_value=(PROFILE, PRIVATE, bundle)), \
                    patch('chrome_job_import.JobStore') as store, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(), 4)
            store.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())['status'], 'control_agent_paused')

    def test_cli_imports_one_local_export_without_printing_applicant_or_job_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = capture(); data['captured_at'] = datetime.now(timezone.utc).isoformat()
            for name, value in (('public', PUBLIC), ('private', PRIVATE), ('capture', data)):
                (root / (name + '.json')).write_text(json.dumps(value))
            argv = ['chrome_job_import.py', '--file', str(root / 'capture.json'), '--profile', str(root / 'public.json'),
                    '--private-profile', str(root / 'private.json'), '--policy', str(ROOT / 'config/automation_policy.production.json'),
                    '--db', str(root / 'jobs.db'), '--report', str(root / 'report.json')]
            with patch.object(sys, 'argv', argv), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result['qualified'], 1)
            self.assertNotIn('Fixture', output.getvalue())
            self.assertNotIn(PRIVATE['email'], output.getvalue())
            self.assertFalse(json.loads((root / 'report.json').read_text())['submission_enabled'])


if __name__ == '__main__':
    unittest.main()
