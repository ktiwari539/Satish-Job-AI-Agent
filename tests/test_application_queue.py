"""Real SQLite concurrency/restarts; synthetic jobs and applicant evidence only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from application_queue import ApplicationQueue, QueueError, canonical_queue_job
from automation_policy import load_automation_policy
from models import Job
from store import JobStore
from submission_engine import record_confirmed_submission, SubmissionResult

REVISION = 'a'*64
NOW = datetime(2026, 10, 29, 5, tzinfo=timezone.utc)  # 10:30 IST
EVIDENCE = dict(flow_state='REVIEW_INSPECTED',exact_job_verified=True, form_exercised=True, identity_verified=True,
    submit_control_verified=True, resume_evidence_state='matching_resume_selected',
    unknown_required_count=0, review_mismatch_count=0, submission_enabled=False, submitted=0, confirmed=0)


def job(number=1, **changes):
    base = Job('linkedin', str(9100000000+number), 'Fixture Employer '+str(number),
        'Customer Success Manager', 'India', 'https://www.linkedin.com/jobs/view/'+str(9100000000+number)+'/',
        'Customer success onboarding SLA stakeholder management. '*12,
        required_skills=('customer success','onboarding','sla'), minimum_years=5)
    return replace(base, **changes)


class ApplicationQueueTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = str(Path(self.folder.name)/'jobs.db')
        self.store = JobStore(self.path)
        self.now = 1000
        self.queue = ApplicationQueue(self.store, clock=lambda: self.now)
        self.policy = replace(load_automation_policy(str(ROOT/'config/automation_policy.production.json')), daily_success_cap=2)

    def enqueue(self, target=None): return self.queue.enqueue(target or job(), REVISION)
    def claim(self, **kw): return self.queue.claim(sources=('linkedin','indeed'), **kw)
    def state(self): return self.queue.snapshot()['jobs'][0]['state']

    def test_canonical_identity_is_idempotent_without_tracking_or_company_key_changes(self):
        identifier = self.enqueue()
        self.assertEqual(self.enqueue(replace(job(),url=job().url+'?tracking=private-value')), identifier)
        self.assertEqual(len(self.queue.snapshot()['jobs']),1)
        self.assertNotIn('private-value',json.dumps(self.queue.snapshot()))
        with self.assertRaises(QueueError): self.enqueue(replace(job(),external_id='9100000002'))

    def test_account_homepage_and_ambiguous_id_cannot_enter_queue(self):
        for target in (replace(job(),url='https://linkedin.com/jobs/search/'),
                       replace(job(),source='indeed',external_id='0123456789abcdef',url='https://in.indeed.com/account/login?jk=0123456789abcdef'),
                       replace(job(),source='naukri',url='https://www.naukri.com/mnjuser/homepage'),
                       replace(job(),url='https://evil.invalid/jobs/view/9100000001/'),
                       replace(job(),url=job().url+'?currentJobId=9100000002'),
                       replace(job(),source='greenhouse',external_id='123',url='https://boards.greenhouse.io/fixture/jobs/123?gh_jid=456')):
            with self.assertRaises(QueueError): self.enqueue(target)
        self.assertEqual(self.queue.snapshot()['jobs'],[])

    def test_job_import_is_atomic_on_identity_collision(self):
        self.enqueue()
        with self.assertRaises(QueueError):
            self.queue.enqueue_many([job(2),replace(job(),external_id='9100000003')],REVISION)
        self.assertEqual(len(self.queue.snapshot()['jobs']),1)

    def test_repeated_search_snippet_does_not_downgrade_or_requeue_full_jd(self):
        self.enqueue();lease=self.claim();self.queue.eligible(lease,job());self.queue.finish(lease,'PREPARED',evidence=EVIDENCE)
        self.enqueue(replace(job(),description='',required_skills=(),minimum_years=None,location=''))
        self.assertEqual(self.state(),'PREPARED');self.assertIsNone(self.claim())

    def test_company_missing_at_discovery_requires_exact_enrichment_before_eligibility(self):
        target=replace(job(),company='')
        self.enqueue(target);lease=self.claim()
        with self.assertRaisesRegex(QueueError,'company_unverified'):self.queue.eligible(lease,target)
        self.queue.eligible(lease,job());self.queue.finish(lease,'PREPARED',evidence=EVIDENCE)
        self.assertEqual(self.queue.snapshot()['jobs'][0]['company'],job().company)

    def test_metadata_free_rediscovery_cannot_erase_recovered_company_or_short_full_jd(self):
        target=replace(job(),description='Customer success onboarding SLA. '*5)
        self.enqueue(target);lease=self.claim();self.queue.eligible(lease,target)
        self.queue.finish(lease,'PREPARED',evidence=EVIDENCE)
        self.enqueue(replace(target,company='',location='',description='',required_skills=()))
        self.assertEqual(self.state(),'PREPARED');self.assertIsNone(self.claim())

    def test_preparation_pause_survives_new_store_and_process(self):
        self.enqueue()
        command=[sys.executable,str(ROOT/'src/agent_backend.py'),'--db',self.path,'--policy',str(ROOT/'config/automation_policy.production.json'),'pause']
        result=subprocess.run(command,capture_output=True,text=True,check=True)
        self.assertTrue(json.loads(result.stdout)['paused'])
        self.assertIsNone(self.claim())
        fresh=ApplicationQueue(JobStore(self.path));fresh.set_paused(False)
        self.assertIsNotNone(self.claim())

    def test_concurrent_workers_receive_distinct_leases(self):
        for number in range(1,9): self.enqueue(job(number))
        def claim(_): return ApplicationQueue(JobStore(self.path),clock=lambda:1000).claim(sources=('linkedin',))
        with ThreadPoolExecutor(max_workers=8) as pool: leases=list(pool.map(claim,range(8)))
        self.assertEqual(len({lease.id for lease in leases}),8)
        self.assertEqual(self.queue.snapshot()['counts']['PREPARING'],8)

    def test_process_exit_recovers_only_preparation_and_fences_the_old_worker(self):
        self.enqueue()
        script="import sys,json;sys.path.insert(0,sys.argv[1]);from application_queue import ApplicationQueue;from store import JobStore;q=ApplicationQueue(JobStore(sys.argv[2]),clock=lambda:1000);a=q.claim(sources=('linkedin',),lease_seconds=1);print(json.dumps(dict(id=a.id,token=a.token)))"
        result=subprocess.run([sys.executable,'-c',script,str(ROOT/'src'),self.path],capture_output=True,text=True,check=True)
        old=json.loads(result.stdout);self.now=1002
        lease=self.claim()
        self.assertEqual(lease.id,old['id']);self.assertNotEqual(lease.token,old['token'])
        with self.assertRaisesRegex(QueueError,'stale'):
            self.queue.finish(replace(lease,token=old['token']),'NEEDS_INPUT')
        self.queue.finish(lease,'NEEDS_INPUT','unknown_required_answer')

    def test_preparation_crash_retries_are_bounded_and_do_not_create_success(self):
        self.enqueue()
        for _ in range(3):
            self.assertIsNotNone(self.claim(lease_seconds=1));self.now+=2
        self.assertIsNone(self.claim())
        self.assertEqual(self.state(),'NEEDS_INPUT')
        self.assertEqual(self.queue.snapshot()['counts']['CONFIRMED'],0)

    def test_prepared_state_requires_eligibility_and_complete_adapter_evidence(self):
        self.enqueue();lease=self.claim()
        with self.assertRaisesRegex(QueueError,'eligibility'): self.queue.finish(lease,'PREPARED',evidence=EVIDENCE)
        self.queue.eligible(lease,job())
        for field,value in (('identity_verified',False),('resume_evidence_state','attachment_unverified'),
                            ('unknown_required_count',1),('submitted',1),('confirmed',False)):
            with self.assertRaisesRegex(QueueError,'evidence'):
                self.queue.finish(lease,'PREPARED',evidence={**EVIDENCE,field:value})
        self.queue.finish(lease,'PREPARED',evidence=EVIDENCE)
        self.assertEqual(self.state(),'PREPARED');self.assertIsNone(self.claim())

    def test_changed_inputs_retry_blocked_work_but_unchanged_inputs_do_not(self):
        self.enqueue();lease=self.claim();self.queue.finish(lease,'NEEDS_INPUT','unknown_required_answer')
        self.enqueue();self.assertIsNone(self.claim())
        self.queue.refresh_revision('b'*64,('linkedin',));new=self.claim()
        self.assertEqual(new.facts_revision,'b'*64);self.assertEqual(new.attempts,1)

    def test_submitted_uncertain_work_is_never_reclaimed_or_reset_by_facts(self):
        self.assertTrue(self.store.reserve_submission_attempt(job()))
        self.enqueue();self.assertEqual(self.state(),'SUBMISSION_UNCERTAIN')
        self.queue.refresh_revision('b'*64,('linkedin',));self.now+=100000
        self.assertIsNone(self.claim());self.assertEqual(self.state(),'SUBMISSION_UNCERTAIN')

    def test_known_manual_exclusion_and_application_ledger_cannot_be_retried(self):
        excluded=replace(job(),external_id='4482859467',url='https://www.linkedin.com/jobs/view/4482859467/')
        self.enqueue(excluded);self.queue.refresh_revision('b'*64,('linkedin',))
        self.assertIsNone(self.claim());self.assertEqual(self.state(),'SKIPPED')
        self.store.mark_applied(job(2));self.enqueue(job(2))
        self.assertIsNone(self.claim());self.assertEqual(self.queue.snapshot()['counts']['SKIPPED'],2)

    def test_cross_portal_same_role_is_prepared_once_across_restarts(self):
        original=job();self.enqueue(original);lease=self.claim()
        self.queue.eligible(lease,original);self.queue.finish(lease,'PREPARED',evidence=EVIDENCE)
        other=replace(original,source='indeed',external_id='0123456789abcdef',url='https://in.indeed.com/viewjob?jk=0123456789abcdef')
        self.enqueue(other);fresh=ApplicationQueue(JobStore(self.path),clock=lambda:1000)
        self.assertIsNone(fresh.claim(sources=('indeed',)))
        self.assertEqual(fresh.snapshot()['counts']['SKIPPED'],1)

    def test_legacy_reservations_survive_additive_schema_upgrade(self):
        path=str(Path(self.folder.name)/'legacy.db')
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE submission_attempts(source TEXT,external_id TEXT,url TEXT UNIQUE,reserved_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(source,external_id))')
            conn.execute('INSERT INTO submission_attempts(source,external_id,url) VALUES(?,?,?)',(job().source,job().external_id,job().url))
        fresh=ApplicationQueue(JobStore(path));fresh.enqueue(job(),REVISION)
        self.assertIsNone(fresh.claim(sources=('linkedin',)))
        self.assertEqual(fresh.snapshot()['counts']['SUBMISSION_UNCERTAIN'],1)

    def test_daily_capacity_is_reserved_atomically_across_concurrent_workers(self):
        def reserve(number): return JobStore(self.path).reserve_submission_attempt(job(number),policy=self.policy,now=NOW)
        with ThreadPoolExecutor(max_workers=8) as pool: accepted=list(pool.map(reserve,range(1,9)))
        self.assertEqual(sum(accepted),2)
        capacity=self.store.submission_budget(self.policy,now=NOW)
        self.assertEqual(capacity['day'],dict(confirmed=0,held=2,used=2))
        self.assertEqual(capacity['remaining_day'],0)

    def test_uncertain_reservations_hold_capacity_without_becoming_successes(self):
        self.assertTrue(self.store.reserve_submission_attempt(job(),policy=self.policy,now=NOW))
        self.assertFalse(record_confirmed_submission(self.store,job(),SubmissionResult('UNCERTAIN')))
        capacity=self.store.submission_budget(self.policy,now=NOW)
        self.assertEqual((capacity['day']['confirmed'],capacity['day']['held']),(0,1))

    def test_quota_preflight_reports_reserved_capacity_as_pending_not_confirmed(self):
        from quota import evaluate_application_quota
        from job_agent_cli import _pilot_quota_preflight
        policy=replace(self.policy,daily_success_cap=1)
        self.assertTrue(self.store.reserve_submission_attempt(job(),policy=policy,now=NOW))
        quota=evaluate_application_quota(policy,self.store,now=NOW)
        self.assertFalse(quota.allowed)
        self.assertEqual((quota.daily_confirmed,quota.daily_reserved,quota.remaining_day),(0,1,0))
        self.assertEqual(quota.reason,'daily_submission_capacity_reserved')
        result=_pilot_quota_preflight(policy,self.store,now=NOW,testing_mode=True,allow_outside_window=True)
        self.assertEqual(result['status'],'daily_submission_capacity_reserved')

    def test_confirmation_replaces_hold_and_updates_queue_without_double_counting(self):
        self.enqueue();lease=self.claim();self.queue.eligible(lease,job());self.queue.finish(lease,'PREPARED',evidence=EVIDENCE)
        self.assertTrue(self.store.reserve_submission_attempt(job(),policy=self.policy,now=NOW))
        result=SubmissionResult('CONFIRMED',confirmed=True,evidence='fixture_positive_confirmation')
        self.assertTrue(record_confirmed_submission(self.store,job(),result))
        # Set a deterministic timestamp in the synthetic ledger, not a portal.
        with sqlite3.connect(self.path) as conn: conn.execute('UPDATE applications SET applied_at=?',(NOW.strftime('%Y-%m-%d %H:%M:%S'),))
        self.assertEqual(self.state(),'CONFIRMED')
        self.assertEqual(self.store.submission_budget(self.policy,now=NOW)['day'],dict(confirmed=1,held=0,used=1))
        self.assertFalse(self.store.reserve_submission_attempt(job(),policy=self.policy,now=NOW))

    def test_window_capacity_pause_and_disabled_policy_are_enforced_at_reservation(self):
        window=replace(self.policy.windows[0],target_successes=1)
        policy=replace(self.policy,daily_success_cap=5,windows=(window,))
        self.queue.set_paused(True)
        self.assertFalse(self.store.reserve_submission_attempt(job(),policy=policy,now=NOW))
        self.queue.set_paused(False)
        self.assertFalse(self.store.reserve_submission_attempt(job(),policy=replace(policy,live_submission_enabled=False),now=NOW))
        self.assertTrue(self.store.reserve_submission_attempt(job(),policy=policy,now=NOW))
        self.assertFalse(self.store.reserve_submission_attempt(job(2),policy=policy,now=NOW))

    def test_cross_source_submission_race_has_only_one_reservation(self):
        first=job();other=replace(first,source='indeed',external_id='0123456789abcdef',url='https://in.indeed.com/viewjob?jk=0123456789abcdef')
        def reserve(target): return JobStore(self.path).reserve_submission_attempt(target,policy=self.policy,now=NOW)
        with ThreadPoolExecutor(max_workers=2) as pool: accepted=list(pool.map(reserve,(first,other)))
        self.assertEqual(sum(accepted),1)

    def test_operational_day_holds_span_midnight_and_roll_over_at_configured_start(self):
        evening=datetime(2026,10,29,18,0,tzinfo=timezone.utc) # 23:30 IST
        after_midnight=datetime(2026,10,29,19,0,tzinfo=timezone.utc) # 00:30 IST
        next_start=datetime(2026,10,30,4,30,tzinfo=timezone.utc)
        self.assertTrue(self.store.reserve_submission_attempt(job(),policy=self.policy,now=evening))
        self.assertEqual(self.store.submission_budget(self.policy,now=after_midnight)['day']['held'],1)
        self.assertEqual(self.store.submission_budget(self.policy,now=next_start)['day']['held'],0)
        self.assertFalse(self.store.reserve_submission_attempt(job(),policy=self.policy,now=next_start))


if __name__ == '__main__': unittest.main()
