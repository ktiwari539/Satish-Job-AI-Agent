import sys
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from portal_preparation import prepare_portal_job, PreparationEvidence
from certify_portals import run_on_page
from test_review_runner import PROFILE, qualified_job
from browser_runtime import BrowserRuntimeUnavailable
from store import JobStore


class PortalPreparationSafety(unittest.TestCase):
    def test_invalid_resume_or_unverified_portal_never_opens_an_application(self):
        job=replace(qualified_job('123'),source='naukri',url='https://www.naukri.com/job-listings-fixture-123')
        with patch('portal_preparation.bounded_goto') as navigate:
            result=prepare_portal_job(MagicMock(),job,{},resume_path='/nonexistent/fixture.pdf')
        self.assertEqual(result.reason,'invalid_resume_file')
        navigate.assert_not_called()

    def test_naukri_restricted_eligibility_remains_a_human_fact_gate(self):
        with tempfile.TemporaryDirectory() as root:
            resume=Path(root)/'fixture.pdf'; resume.write_bytes(b'%PDF fixture')
            job=replace(qualified_job('123'),source='naukri',title='Customer Success Manager - Female only',url='https://www.naukri.com/job-listings-fixture-123')
            with patch('portal_preparation.bounded_goto') as navigate:
                result=prepare_portal_job(MagicMock(),job,{},resume_path=str(resume),applicant_experience_years=8)
        self.assertEqual(result.reason,'restricted_eligibility_needs_human_review')
        navigate.assert_not_called()

    def test_partial_evidence_survives_browser_loss_and_no_later_job_is_attempted(self):
        with tempfile.TemporaryDirectory() as root:
            jobs=[replace(qualified_job(str(i)),source='lever',company='Fixture '+str(i),url='https://jobs.lever.co/fixture/'+str(i)) for i in (1,2,3)]
            page=MagicMock(); page.is_closed.return_value=False
            args=SimpleNamespace(portals=('lever',),sources='fixture_sources.json',max_jobs=10,query='Customer Success Manager',location='India',threshold=75,resume_path='fixture.pdf')
            def navigate(page,url): page.url=url
            with patch('certify_portals._discover_public_portal',return_value=(jobs,[])), \
                 patch('certify_portals.bounded_goto',side_effect=navigate), \
                 patch('verified_jd._read_first_visible',return_value=jobs[0].description), \
                 patch('certify_portals.prepare_portal_job',side_effect=[PreparationEvidence('READY_FOR_REVIEW',form_exercised=True),BrowserRuntimeUnavailable(reason_code='browser_connection_lost')]) as prepare:
                report=run_on_page(page,args,PROFILE,dict(full_name='Fixture Applicant',email='fixture@example.invalid',phone='2025550123'),JobStore(str(Path(root)/'jobs.db')))
        self.assertEqual(prepare.call_count,2)
        self.assertTrue(report['partial_results'])
        self.assertEqual(report['reason_code'],'browser_connection_lost')
        self.assertEqual(len(report['application_evidence']),1)
        self.assertEqual(report['submitted'],0)

    def test_browser_closing_during_last_form_is_global_and_creates_no_cooldown(self):
        with tempfile.TemporaryDirectory() as root:
            job=replace(qualified_job('1'),source='lever',url='https://jobs.lever.co/fixture/1')
            page=MagicMock(); page.is_closed.return_value=False
            args=SimpleNamespace(portals=('lever',),sources='fixture_sources.json',max_jobs=10,query='Customer Success Manager',location='India',threshold=75,resume_path='fixture.pdf')
            def navigate(page,url): page.url=url
            def closed_form(*args,**kwargs):
                page.is_closed.return_value=True
                return PreparationEvidence('BLOCKED','inspection_failed')
            store=JobStore(str(Path(root)/'jobs.db'))
            with patch('certify_portals._discover_public_portal',return_value=([job],[])), \
                 patch('certify_portals.bounded_goto',side_effect=navigate), \
                 patch('verified_jd._read_first_visible',return_value=job.description), \
                 patch('certify_portals.prepare_portal_job',side_effect=closed_form), \
                 patch.object(store,'record_preparation_attempt') as record:
                report=run_on_page(page,args,PROFILE,dict(full_name='Fixture Applicant',email='fixture@example.invalid',phone='2025550123'),store)
            record.assert_not_called()
        self.assertEqual(report['status'],'cross_portal_environment_blocked')
        self.assertEqual(report['reason_code'],'browser_connection_lost')
        self.assertEqual(report['application_evidence'],[])
