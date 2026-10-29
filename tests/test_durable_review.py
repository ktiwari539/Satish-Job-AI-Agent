"""Integration of durable SQLite work with the shared qualification runner."""
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from application_queue import ApplicationQueue
from browser_runtime import BrowserRuntimeUnavailable
from durable_review import run_durable_review_batch
from jd_enrichment import EnrichmentResult
from models import CandidateProfile
from portal_preparation import PreparationEvidence
from review_runner import ReviewPreparationResult
from store import JobStore
from test_application_queue import job, REVISION, EVIDENCE

PROFILE=CandidateProfile.from_dict(dict(target_roles=['Customer Success Manager'],
    skills=['customer success','onboarding','sla'],total_experience_years=8,
    india_authorized=True,remote_allowed=True))


def ready(): return PreparationEvidence('READY_FOR_REVIEW',**EVIDENCE)


class DurableReviewTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.store=JobStore(str(Path(self.folder.name)/'jobs.db'))
        self.queue=ApplicationQueue(self.store)

    def run_batch(self,jobs,prepare=lambda j,p:ready(),enrich=lambda j:EnrichmentResult(j,True),**kw):
        return run_durable_review_batch(jobs,queue=self.queue,sources=('linkedin',),revision=kw.pop('revision',REVISION),
            max_jobs=kw.pop('max_jobs',20),profile=PROFILE,private_profile={},threshold=75,cooldown_days=90,
            enrich_job=enrich,prepare_job=prepare,**kw)

    def test_unknown_job_advances_to_next_job_and_resume_never_repeats_finished_work(self):
        seen=[]
        def prepare(target,facts):
            seen.append(target.external_id)
            return PreparationEvidence('BLOCKED','unknown_required_answer') if target.external_id==job().external_id else ready()
        result,stop=self.run_batch([job(),job(2)],prepare)
        self.assertEqual((result.blocked,result.ready_for_review,stop),(1,1,''))
        self.assertEqual(self.queue.snapshot()['counts']['NEEDS_INPUT'],1)
        self.assertEqual(self.queue.snapshot()['counts']['PREPARED'],1)
        self.run_batch([],prepare)
        self.assertEqual(seen,[job().external_id,job(2).external_id])

    def test_process_restart_resumes_unfinished_discoveries_with_current_facts(self):
        self.run_batch([job(),job(2)],max_jobs=1)
        self.queue=ApplicationQueue(JobStore(self.store.path))
        result,_=self.run_batch([])
        self.assertEqual(result.ready_for_review,1)
        self.assertEqual(self.queue.snapshot()['counts']['PREPARED'],2)

    def test_plain_ready_string_cannot_become_prepared_without_release_evidence(self):
        result,_=self.run_batch([job()],lambda j,p:ReviewPreparationResult('READY_FOR_REVIEW'))
        self.assertEqual(result.ready_for_review,0)
        self.assertEqual(self.queue.snapshot()['jobs'][0]['state'],'NEEDS_INPUT')
        self.assertEqual(self.queue.snapshot()['jobs'][0]['reason_code'],'preparation_evidence_incomplete')

    def test_pause_during_enrichment_defers_without_touching_form_or_using_attempt(self):
        seen=[]
        def enrich(target):
            self.queue.set_paused(True)
            return EnrichmentResult(target,True)
        result,stop=self.run_batch([job()],lambda j,p:seen.append(j),enrich=enrich)
        self.assertEqual(stop,'queue_paused');self.assertEqual(seen,[])
        self.assertEqual(self.queue.snapshot()['jobs'][0]['state'],'QUEUED')
        self.assertEqual(self.queue.snapshot()['jobs'][0]['attempts'],0)
        self.queue.set_paused(False)
        self.assertEqual(self.run_batch([])[0].ready_for_review,1)

    def test_changed_or_unavailable_controls_stop_before_form_and_preserve_work(self):
        for reason in ('control_inputs_changed','current_controls_unavailable','control_agent_paused'):
            self.queue.refresh_revision('b'*64,('linkedin',))
            checks=[];seen=[]
            def gate():
                checks.append(1)
                return '' if len(checks)==1 else reason
            _,stop=self.run_batch([job()],lambda j,p:seen.append(j),control_check=gate)
            self.assertEqual(stop,reason);self.assertEqual(seen,[])
            self.assertEqual(self.queue.snapshot()['counts']['QUEUED'],1)

    def test_browser_loss_stops_globally_with_bounded_retry_and_preserved_next_job(self):
        def lost(j,p): raise BrowserRuntimeUnavailable(reason_code='browser_connection_lost')
        with self.assertRaises(BrowserRuntimeUnavailable): self.run_batch([job(),job(2)],lost)
        state=self.queue.snapshot()['counts']
        self.assertEqual((state['RETRY_WAIT'],state['QUEUED'],state['CONFIRMED']),(1,1,0))

    def test_job_specific_exception_does_not_block_another_job(self):
        def prepare(target,facts):
            if target.external_id==job().external_id: raise RuntimeError('private answer must not be stored')
            return ready()
        result,_=self.run_batch([job(),job(2)],prepare)
        self.assertEqual((result.blocked,result.ready_for_review),(1,1))
        self.assertNotIn('private answer',str(self.queue.snapshot()))

    def test_enrichment_cannot_change_the_claimed_job_identity(self):
        result,_=self.run_batch([job()],enrich=lambda j:EnrichmentResult(job(2),True))
        self.assertEqual(result.ready_for_review,0)
        self.assertEqual(result.skipped_jd,1)

    def test_reviewed_input_change_revalidates_blocked_and_prepared_jobs(self):
        self.run_batch([job()],lambda j,p:PreparationEvidence('BLOCKED','unknown_required_answer'))
        result,_=self.run_batch([],revision='b'*64)
        self.assertEqual(result.ready_for_review,1)

    def test_certification_runner_uses_queue_and_reuses_it_after_restart(self):
        from certify_portals import run_on_page
        target=replace(job(),source='greenhouse',external_id='123456',url='https://boards.greenhouse.io/fixture/jobs/123456')
        args=SimpleNamespace(portals=('greenhouse',),sources='fixture.json',max_jobs=10,threshold=75,
                             query='Customer Success Manager',resume_path=str(Path(self.folder.name)/'resume.pdf'))
        Path(args.resume_path).write_bytes(b'%PDF-1.4 synthetic fixture')
        private=dict(full_name='Fixture Applicant',email='fixture@example.invalid',phone='2025550123')
        page=SimpleNamespace(is_closed=lambda:False)
        with patch('certify_portals._discover_public_portal',return_value=([target],[])), \
             patch('certify_portals.bounded_goto'),patch('certify_portals.exact_job_page',return_value=True), \
             patch('certify_portals.read_verified_job_description',return_value=(EnrichmentResult(target,True),{})), \
             patch('certify_portals.prepare_portal_job',return_value=ready()) as prepare:
            first=run_on_page(page,args,PROFILE,private,self.store,queue=self.queue)
            second=run_on_page(page,args,PROFILE,private,self.store,queue=ApplicationQueue(JobStore(self.store.path)))
        self.assertEqual(first['preparation']['ready_for_review'],1)
        self.assertEqual(second['preparation']['ready_for_review'],0)
        self.assertEqual(prepare.call_count,1)
        self.assertEqual(second['queue']['counts']['PREPARED'],1)
        self.assertEqual((first['submitted'],first['confirmed']),(0,0))


if __name__=='__main__': unittest.main()
