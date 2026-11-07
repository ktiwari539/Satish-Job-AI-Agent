import sys
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from test_review_runner import PROFILE, qualified_job, Enrichment
from review_runner import prepare_review_batch, ReviewPreparationResult
from preparation_revision import preparation_revision
from store import JobStore
from browser_runtime import BrowserRuntimeUnavailable


class PreparationHistory(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.db=str(Path(self.folder.name)/'jobs.db'); self.store=JobStore(self.db)
        self.job=qualified_job('9001'); self.calls=0

    def run_batch(self,revision,job=None,fail=False):
        def prepare(job,profile):
            self.calls+=1
            if fail: raise BrowserRuntimeUnavailable(reason_code='browser_connection_lost')
            return ReviewPreparationResult('BLOCKED','unknown_required_answer')
        return prepare_review_batch([job or self.job],profile=PROFILE,private_profile={},threshold=75,cooldown_days=90,
            store=self.store,enrich_job=lambda j:Enrichment(j,True),prepare_job=prepare,preparation_revision=revision)

    def test_unchanged_blocked_form_is_skipped_on_the_next_run(self):
        self.run_batch('facts-v1')
        report=self.run_batch('facts-v1')
        self.assertEqual(self.calls,1)
        self.assertEqual(report.skipped_recent_preparation,1)
        self.assertEqual(report.outcomes[0].status,'SKIPPED_RECENT_PREPARATION')
        self.assertFalse(self.store.is_recent_similar_application(self.job,cooldown_days=0))

    def test_updated_facts_or_job_description_allow_an_immediate_recheck(self):
        self.run_batch('facts-v1'); self.run_batch('facts-v2')
        self.run_batch('facts-v2',replace(self.job,description=self.job.description+' Updated mandatory question.'))
        self.assertEqual(self.calls,3)

    def test_expired_preparation_does_not_create_a_permanent_application_block(self):
        self.run_batch('facts-v1')
        with sqlite3.connect(self.db) as conn: conn.execute("UPDATE preparation_attempts SET checked_at='2000-01-01'")
        self.run_batch('facts-v1')
        self.assertEqual(self.calls,2)
        self.assertFalse(self.store.is_applied(self.job))

    def test_global_browser_failure_does_not_create_a_retry_cooldown(self):
        with self.assertRaises(BrowserRuntimeUnavailable): self.run_batch('facts-v1',fail=True)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM preparation_attempts').fetchone()[0],0)
        self.run_batch('facts-v1')
        self.assertEqual(self.calls,2)

    def test_revision_tracks_verified_answers_and_resume_changes_without_storing_them(self):
        resume=Path(self.folder.name)/'fixture.pdf'; resume.write_bytes(b'%PDF v1')
        a=preparation_revision({'total_experience_years':8},{'email':'fixture@example.invalid'},str(resume))
        b=preparation_revision({'total_experience_years':8},{'email':'new@example.invalid'},str(resume))
        resume.write_bytes(b'%PDF v2')
        c=preparation_revision({'total_experience_years':8},{'email':'new@example.invalid'},str(resume))
        self.assertNotEqual(a,b); self.assertNotEqual(b,c)
        self.assertRegex(a,r'^[0-9a-f]{64}$')
