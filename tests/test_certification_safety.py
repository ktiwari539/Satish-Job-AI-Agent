"""Safety boundaries exercised without any portal or applicant data."""
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from store import JobStore
from models import Job
from resume_store import import_resume, resolve_current_resume
from resume_evidence import _expected_names, inspect_resume_evidence
from smart_queue_history import read_history, record_check, skip_reason
from easy_apply_debug import _local_application_already_recorded
from release_acceptance import review_identity_verified
from browser_portals import linkedin_search_url
from job_agent_cli import _run
from linkedin_entry_diagnostics import classify_linkedin_entry
from submission_engine import SubmissionResult, record_confirmed_submission, submit_linkedin_application, _wait_for_linkedin_confirmation


def job(jid='9000000001'):
    return Job(source='linkedin', external_id=jid, url='https://www.linkedin.com/jobs/view/'+jid+'/',
               company='Fixture', title='Fixture Customer Success Manager', location='India', description='Fixture only')


class CertificationSafety(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = str(Path(self.folder.name) / 'jobs.db')
        self.store = JobStore(self.db)

    def test_atomic_reservation_allows_only_one_concurrent_click(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.store.reserve_submission_attempt(job()), range(4)))
        self.assertEqual(sum(results), 1)
        self.assertTrue(JobStore(self.db).has_submission_attempt(job()))
        self.assertTrue(self.store.is_recent_similar_application(job(), cooldown_days=0))
        self.assertIsNone(self.store.get_confirmed_submission('linkedin', job().external_id))
        self.assertTrue(_local_application_already_recorded(SimpleNamespace(db=self.db), job().url))

    def test_known_manual_job_blocked_even_with_new_database(self):
        known = job('4482859467')
        self.assertTrue(_local_application_already_recorded(SimpleNamespace(db=None), known.url))
        self.assertTrue(self.store.is_recent_similar_application(known))
        self.assertFalse(self.store.reserve_submission_attempt(known))

    def test_confirmed_ledger_write_is_idempotent(self):
        result = SubmissionResult(state='CONFIRMED', confirmed=True, evidence='fixture_confirmation')
        record_confirmed_submission(self.store, job(), result)
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE applications SET applied_at='2026-01-01 00:00:00'")
        record_confirmed_submission(self.store, job(), result)
        row = self.store.get_confirmed_submission('linkedin', job().external_id)
        self.assertEqual(row['applied_at'], '2026-01-01 00:00:00')
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM applications').fetchone()[0], 1)

    def test_applied_history_never_expires_as_cooldown(self):
        record_check(self.db, '9000000001', 'debug_portal_already_applied_skipped', 'NOT_RUN', entry_classification='ALREADY_APPLIED')
        history = read_history(self.db)
        self.assertEqual(skip_reason(history, '9000000001', now=datetime.now(timezone.utc)+timedelta(days=365)), 'already_applied')

    def test_expired_transient_history_allows_reinspection(self):
        record_check(self.db, '9000000001', 'debug_no_easy_apply_entry', 'NOT_RUN', entry_classification='EXTERNAL_APPLY')
        self.assertEqual(skip_reason(read_history(self.db), '9000000001', now=datetime.now(timezone.utc)+timedelta(days=2)), '')

    def test_live_search_flag_cannot_approve_an_unnamed_job(self):
        with patch('job_agent_cli.PlaywrightSession', side_effect=AssertionError('browser must not start')), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(_run(SimpleNamespace(approve_one_live_application=True)), 3)
        self.assertEqual(json.loads(output.getvalue())['status'], 'job_specific_approval_required')

    def test_search_requests_real_easy_apply_filter(self):
        self.assertIn('f_AL=true', linkedin_search_url('Customer Success Manager', 'India', easy_apply_only=True))
        self.assertNotIn('f_AL', linkedin_search_url('Customer Success Manager', 'India'))

    def test_missing_identity_is_not_release_ready(self):
        self.assertFalse(review_identity_verified({}, ()))
        self.assertFalse(review_identity_verified(dict(full_name='Fixture',email='fixture@example.invalid',phone='1'), ('email:matched',)))

    def test_manifest_alias_cannot_certify_tampered_resume(self):
        source = Path(self.folder.name) / 'original.pdf'
        source.write_bytes(b'%PDF-fixture')
        saved = import_resume(str(source), str(Path(self.folder.name) / 'vault'))
        saved.write_bytes(b'tampered')
        self.assertNotIn('original.pdf', _expected_names(str(saved)))
        self.assertEqual(inspect_resume_evidence(SimpleNamespace(), str(saved)), 'resume_provenance_invalid')

    def test_manifest_rejects_path_traversal_and_absent_digest(self):
        root = Path(self.folder.name) / 'vault'
        root.mkdir()
        for name, digest in [('../original.pdf', 'a'*64), ('resume.pdf', '')]:
            (root / 'manifest.json').write_text(json.dumps(dict(current_file=name, sha256=digest)))
            with self.assertRaises(ValueError):
                resolve_current_resume(str(root))

    def test_entry_probe_does_not_reflect_untrusted_strings(self):
        page = SimpleNamespace(url=job().url, evaluate=lambda _: dict(scoped=True, easy_controls='private value', heading_count=1, unknown='secret'))
        result = classify_linkedin_entry(page, job().url)
        self.assertEqual(result['entry_classification'], 'SELECTOR_LAYOUT_FAILURE')
        self.assertNotIn('private', json.dumps(result))
        self.assertNotIn('secret', json.dumps(result))

    def test_confirmation_after_route_changes_cannot_confirm_original_job(self):
        page = SimpleNamespace(url=job('9000000002').url)
        with patch('submission_engine.detect_linkedin_submission_confirmation', return_value='confirmation_dialog:fixture') as probe:
            self.assertEqual(_wait_for_linkedin_confirmation(page, submitted_job_url=job().url), '')
        probe.assert_not_called()

    def test_duplicate_reservation_blocks_click_at_last_boundary(self):
        page, button = SimpleNamespace(url=job().url), SimpleNamespace()
        with patch('submission_engine._active_dialog_root', return_value='.jobs-easy-apply-modal'), \
             patch('submission_engine._visible_submit_control', return_value=(button, 'Submit application')), \
             patch('submission_engine._control_identity', return_value='Submit application'), \
             patch('submission_engine._exact_linkedin_applied_evidence', return_value=''):
            result = submit_linkedin_application(page, live_submission_enabled=True,
                prior_state='SUBMIT_READY', before_click=lambda: False)
        self.assertEqual(result.reason, 'submission_attempt_already_reserved')
        self.assertFalse(result.confirmed)


if __name__ == '__main__':
    unittest.main()
