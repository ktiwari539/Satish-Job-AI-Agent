import sys
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from test_review_runner import PROFILE, qualified_job, Enrichment
from review_runner import prepare_review_batch, ReviewPreparationResult
from store import JobStore
from browser_runtime import BrowserRuntimeUnavailable


class CrossPortalBatchSafety(unittest.TestCase):
    def run_batch(self,jobs,prepare):
        with tempfile.TemporaryDirectory() as root:
            return prepare_review_batch(jobs,profile=PROFILE,private_profile={},threshold=75,cooldown_days=90,
                store=JobStore(str(Path(root)/'jobs.db')),enrich_job=lambda job:Enrichment(job,True),
                prepare_job=prepare,dedupe_within_batch=True)

    def test_same_posting_on_two_portals_is_prepared_once(self):
        a=qualified_job('1')
        b=replace(a,source='indeed',external_id='abc123',url='https://in.indeed.com/viewjob?jk=abc123')
        seen=[]
        def prepare(job,profile):
            seen.append(job.source)
            return ReviewPreparationResult('READY_FOR_REVIEW')
        report=self.run_batch([a,b],prepare)
        self.assertEqual(seen,['linkedin'])
        self.assertEqual(report.skipped_duplicate,1)

    def test_unknown_answer_blocks_only_that_job_and_next_portal_continues(self):
        a=qualified_job('1'); b=replace(a,source='naukri',company='Different Fixture Employer',external_id='2')
        seen=[]
        def prepare(job,profile):
            seen.append(job.source)
            return ReviewPreparationResult('BLOCKED','unknown_required_answer') if job.source=='linkedin' else ReviewPreparationResult('READY_FOR_REVIEW')
        report=self.run_batch([a,b],prepare)
        self.assertEqual(seen,['linkedin','naukri'])
        self.assertEqual(report.ready_for_review,1)
        self.assertEqual(report.blocked,1)

    def test_global_browser_failure_is_not_misreported_as_job_rejections(self):
        def fail(job,profile):
            raise BrowserRuntimeUnavailable(reason_code='browser_connection_lost')
        with self.assertRaises(BrowserRuntimeUnavailable):
            self.run_batch([qualified_job('1'),qualified_job('2')],fail)
