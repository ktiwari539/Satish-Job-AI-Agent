"""Real Chromium and synthetic search layouts. Not authenticated live evidence."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from application_queue import ApplicationQueue
from browser_portals import extract_linkedin_cards
from certify_portals import run_on_page
from linkedin_discovery import discover_search
from models import CandidateProfile,Job
from resume_store import import_resume
from store import JobStore
from portal_preparation import prepare_portal_job

SEARCH='https://www.linkedin.com/jobs/search/?keywords=Customer+Success+Manager&location=India&f_AL=true'
ID='9300000001'
FACTS=dict(full_name='Fixture Applicant',email='fixture@example.invalid',phone='2025550123',location='Fixture City',
           answers={'Are you willing to relocate?':'Yes'})
PROFILE=CandidateProfile.from_dict(dict(target_roles=['customer success manager'],skills=['customer success','onboarding','sla'],
    skill_taxonomy=['customer success','onboarding','sla'],total_experience_years=8,india_authorized=True,remote_allowed=True))


def card(identifier=ID,**kw):
    href=kw.get('href','/jobs/view/'+identifier+'/')
    return '<div class="job-card-container" data-job-id="'+identifier+'"><a class="job-card-list__title--link" href="'+href+'">Customer Success Manager</a><span class="artdeco-entity-lockup__subtitle">Fixture Employer</span><span class="artdeco-entity-lockup__caption">India</span></div>'


class LinkedInDiscoveryFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(headless=True)
        except Exception:
            if os.environ.get('REQUIRE_BROWSER_FIXTURES')=='1':raise
            raise unittest.SkipTest('Install browser fixtures and Chromium')

    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()

    def setUp(self):
        self.context=self.browser.new_context();self.addCleanup(self.context.close)
        self.page=self.context.new_page();self.page.set_default_timeout(1500)
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        source=Path(self.folder.name)/'fixture_resume.pdf';source.write_bytes(b'%PDF-1.4 fixture only')
        self.resume=str(import_resume(str(source),str(Path(self.folder.name)/'vault')))

    def load(self,html,url=SEARCH):
        self.context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=html))
        self.page.goto(url)

    def discover(self,**kwargs):return discover_search(self.page,PROFILE.skill_taxonomy,expected_query='Customer Success Manager',**kwargs)

    def test_stray_first_selector_does_not_hide_a_valid_other_layout(self):
        self.load('<main><li class="scaffold-layout__list-item">Advertisement</li>'+card()+'</main>')
        result=self.discover(timeout_ms=0)
        self.assertEqual(result.status,'DISCOVERED');self.assertEqual(len(result.jobs),1)
        self.assertEqual(result.evidence['legacy_containers'],2)
        self.assertEqual(result.evidence['verified_cards'],1)
        self.assertEqual(len(extract_linkedin_cards(self.page)),1)

    def test_semantic_job_id_without_href_and_excluded_details_sidebar(self):
        self.load('<main><div role="listitem" data-occludable-job-id="'+ID+'"><h3>Customer Success Manager</h3><span data-testid="company-name">Fixture Employer</span><span data-testid="job-location">India</span><button onclick="window.clicks++">Select</button></div><aside>'+card('9300000002')+'</aside><section class="jobs-details">'+card('9300000003')+'</section></main><script>window.clicks=0</script>')
        result=self.discover(timeout_ms=0)
        self.assertEqual([j.external_id for j in result.jobs],[ID])
        self.assertEqual(self.page.evaluate('window.clicks'),0)

    def test_slug_tracking_hidden_copies_and_conflicting_ids_are_validated(self):
        one=card(href='/jobs/view/customer-success-manager-at-fixture-'+ID+'/?trk=private-token#section')
        one=one.replace('>Customer Success Manager</a>','>Customer Success Manager<span class="visually-hidden">Customer Success Manager</span><span aria-hidden="true">Verified</span></a>')
        self.load('<main>'+one+'<section style="display:none">'+card('9300000002')+'</section>'+card('9300000003',href='/jobs/view/9300000004/')+'</main>')
        result=self.discover(timeout_ms=0)
        self.assertEqual([j.external_id for j in result.jobs],[ID])
        self.assertEqual(result.jobs[0].title,'Customer Success Manager')
        self.assertEqual(result.jobs[0].url,'https://www.linkedin.com/jobs/view/'+ID+'/')
        self.assertGreater(result.evidence['identity_conflicts'],0)
        self.assertNotIn('private-token',json.dumps(result.evidence))

    def test_hydration_later_than_old_three_second_wait_is_discovered(self):
        html='<main><section data-testid="job-search-results" aria-busy="true"><div role="progressbar">Loading</div></section></main><script>setTimeout(()=>{const root=document.querySelector("section");root.innerHTML='+json.dumps(card())+';root.setAttribute("aria-busy","false");window.hydrated=true},4300)</script>'
        self.load(html)
        result=self.discover(timeout_ms=6000,poll_ms=200)
        self.assertEqual((result.status,len(result.jobs)),('DISCOVERED',1))
        self.assertTrue(self.page.evaluate('window.hydrated'))
        self.assertGreater(result.evidence['attempts'],10)

    def test_explicit_no_results_does_not_borrow_recommendations(self):
        self.load('<main><h2>No matching jobs</h2><aside>'+card()+'</aside></main>')
        result=self.discover(timeout_ms=1000)
        self.assertEqual((result.status,result.jobs,result.evidence['attempts']),('SEARCH_NO_RESULTS',(),1))

    def test_multi_job_wrapper_does_not_poison_independent_anchor_identities(self):
        self.load('<main><article role="listitem"><a href="/jobs/view/'+ID+'/">Customer Success Manager</a><a href="/jobs/view/9300000002/">Technical Account Manager</a></article></main>')
        result=self.discover(timeout_ms=0)
        self.assertEqual({j.external_id for j in result.jobs},{ID,'9300000002'})
        self.assertTrue(all(j.company=='' and j.location=='' for j in result.jobs))

    def test_visible_auth_is_classified_and_hidden_password_footer_is_ignored(self):
        self.load('<main><h2>Sign in to LinkedIn</h2><input type="password" value="private-value"><input type="email" value="private@example.invalid"></main>')
        result=self.discover(timeout_ms=0)
        self.assertEqual(result.status,'SEARCH_LOGIN_REQUIRED')
        self.assertNotIn('private',json.dumps(result.evidence))
        self.context.unroute('**/*')
        self.load('<main>'+card()+'</main><footer>Protected by reCAPTCHA<form action="/login" style="display:none"><input type="password"></form></footer>')
        self.assertEqual(self.discover(timeout_ms=0).status,'DISCOVERED')

    def args(self):return SimpleNamespace(portals=('linkedin',),query='Customer Success Manager',location='India',max_jobs=10,
                                          sources='',threshold=75,resume_path=self.resume)

    def test_search_login_failure_preserves_pending_queue_and_reports_discovery_block(self):
        def respond(route):
            html='<nav>Jobs My Network Messaging</nav>' if '/feed/' in route.request.url else '<main><h2>Sign in to LinkedIn</h2></main>'
            route.fulfill(status=200,content_type='text/html',body=html)
        self.context.route('**/*',respond)
        store=JobStore(str(Path(self.folder.name)/'jobs.db'));queue=ApplicationQueue(store)
        queue.enqueue(Job('linkedin',ID,'Fixture','Customer Success Manager','India','https://www.linkedin.com/jobs/view/'+ID+'/',''),'a'*64)
        with patch('certify_portals.prepare_portal_job',side_effect=AssertionError('must not fill after authentication loss')):
            report=run_on_page(self.page,self.args(),PROFILE,FACTS,store,queue=queue)
        self.assertEqual(report['status'],'cross_portal_discovery_blocked')
        self.assertEqual(report['portal_results'][0]['status'],'SEARCH_LOGIN_REQUIRED')
        self.assertEqual(report['queue']['counts']['QUEUED'],1)
        self.assertEqual((report['preparation']['discovered'],report['submitted']),(0,0))
        self.assertTrue(Path(report['portal_results'][0]['discovery_report']).is_file())

    def test_semantic_anchor_metadata_is_recovered_from_exact_page_before_review(self):
        wizard=(ROOT/'tests/fixtures/linkedin_wizard.html').read_text()
        header='<div class="job-details-jobs-unified-top-card__job-title"><h1>Customer Success Manager</h1></div><div class="job-details-jobs-unified-top-card__company-name"><a>Fixture Recovery Employer</a></div><div class="job-details-jobs-unified-top-card__primary-description-container">Pune, India</div><section class="jobs-description__content">'+('Customer success onboarding SLA stakeholder management. '*10)+'</section>'
        wizard=wizard.replace('<main>','<main>'+header,1)
        def respond(route):
            path=urlsplit(route.request.url).path
            html=('<nav>Jobs My Network Messaging</nav>' if path=='/feed/' else
                  '<main><a href="/jobs/view/'+ID+'/">Customer Success Manager</a></main>' if path.rstrip('/')=='/jobs/search' else wizard)
            route.fulfill(status=200,content_type='text/html',body=html)
        self.context.route('**/*',respond)
        store=JobStore(str(Path(self.folder.name)/'jobs.db'));queue=ApplicationQueue(store)
        report=run_on_page(self.page,self.args(),PROFILE,FACTS,store,queue=queue)
        self.assertEqual(report['preparation']['ready_for_review'],1,report)
        self.assertEqual(report['jd_evidence'][0]['read_route'],'exact_job_metadata_recovery')
        self.assertEqual(self.page.evaluate('window.submitClicks'),0)
        self.assertEqual(report['queue']['jobs'][0]['company'],'Fixture Recovery Employer')
        with sqlite3.connect(store.path) as conn:stored=json.loads(conn.execute('SELECT job_json FROM agent_queue_jobs').fetchone()[0])
        self.assertEqual(stored['location'],'Pune, India')
        repeated=run_on_page(self.page,self.args(),PROFILE,FACTS,store,queue=ApplicationQueue(JobStore(store.path)))
        self.assertEqual(repeated['status'],'queue_no_pending_work')
        self.assertEqual(repeated['queue']['counts']['PREPARED'],1)
        self.assertEqual(repeated['preparation']['ready_for_review'],0)
        evidence=dict(verification_scope='synthetic_chromium_search_to_durable_review_not_live_linkedin',
            discovered=1,metadata_recovered_from_exact_job=True,prepared=1,repeated_preparations=0,submitted=0,confirmed=0,
            diagnostic=report['portal_results'][0]['discovery'])
        artifact=ROOT/'data/linkedin_discovery_fixture_acceptance.json';artifact.parent.mkdir(exist_ok=True)
        artifact.write_text(json.dumps(evidence,sort_keys=True,indent=2)+'\n')

    def test_complete_cards_survive_slug_route_changes_and_advance_after_unknown_answer(self):
        identifiers=(ID,'9300000002')
        wizard=(ROOT/'tests/fixtures/linkedin_wizard.html').read_text()
        def respond(route):
            path=urlsplit(route.request.url).path
            if path=='/feed/':html='<nav>Jobs My Network Messaging</nav>'
            elif path.rstrip('/')=='/jobs/search':
                html='<main>'+''.join(card(identifier).replace('Fixture Employer','Fixture Employer '+identifier) for identifier in identifiers)+'</main>'
            else:
                identifier=next(i for i in identifiers if i in path)
                header='<div class="job-details-jobs-unified-top-card__job-title"><h1>Customer Success Manager</h1></div><div class="job-details-jobs-unified-top-card__company-name">Fixture Employer '+identifier+'</div><section class="jobs-description__content">'+('Customer success onboarding SLA stakeholder management. '*10)+'</section>'
                changed='/jobs/view/customer-success-manager-at-fixture-'+identifier+'/?currentJobId='+identifier+'&layout=inline'
                html='<script>history.replaceState(null,"",'+json.dumps(changed)+')</script>'+wizard.replace('<main>','<main>'+header,1)
                if identifier==ID:html=html.replace("const unknown = new URLSearchParams(location.search).has('unknown');",'const unknown = true;')
            route.fulfill(status=200,content_type='text/html',body=html)
        self.context.route('**/*',respond)
        store=JobStore(str(Path(self.folder.name)/'jobs.db'));queue=ApplicationQueue(store)
        report=run_on_page(self.page,self.args(),PROFILE,FACTS,store,queue=queue)
        self.assertEqual(report['portal_results'][0]['discovery']['metadata_pending'],0)
        summary=report['preparation']
        self.assertEqual((summary['discovered'],summary['enriched'],summary['qualified'],summary['blocked'],summary['ready_for_review']),(2,2,2,1,1),report)
        self.assertEqual([item['read_route'] for item in report['jd_evidence']],['visible_scoped','visible_scoped'])
        self.assertEqual(len(report['application_evidence']),2)
        self.assertTrue(all(item['form_exercised'] and item['exact_job_verified'] for item in report['application_evidence']))
        self.assertEqual(report['application_evidence'][0]['flow_state'],'BLOCKED_UNKNOWN_REQUIRED_FIELDS')
        ready=report['application_evidence'][1]
        self.assertTrue(ready['identity_verified'] and ready['submit_control_verified'])
        self.assertEqual(ready['resume_evidence_state'],'matching_resume_selected')
        self.assertEqual(self.page.evaluate('window.step'),4)
        self.assertEqual(self.page.evaluate('window.submitClicks'),0)
        self.assertEqual((report['queue']['counts']['NEEDS_INPUT'],report['queue']['counts']['PREPARED']),(1,1))
        evidence=dict(verification_scope='synthetic_chromium_complete_search_cards_to_inline_review_not_live_linkedin',
            discovered=2,jd_verified=2,qualified=2,forms_exercised=2,unknown_answer_blocked=1,
            prepared=1,selected_resume_verified=1,submit_controls_inspected=1,submit_clicks=0,submitted=0,confirmed=0,
            route_variants=['canonical_numeric','slugged_same_id','consistent_currentJobId'])
        artifact=ROOT/'data/linkedin_complete_flow_fixture_acceptance.json';artifact.parent.mkdir(exist_ok=True)
        artifact.write_text(json.dumps(evidence,sort_keys=True,indent=2)+'\n')

    def test_slugged_posting_preserves_exact_applied_control_without_opening_form(self):
        changed='/jobs/view/customer-success-at-fixture-'+ID+'/?currentJobId='+ID
        html='<script>window.clicks=0;history.replaceState(null,"",'+json.dumps(changed)+')</script><main><div class="job-details-jobs-unified-top-card" data-job-id="'+ID+'"><h1>Fixture job</h1><button onclick="window.clicks++">Applied</button></div></main>'
        self.load(html)
        job=Job('linkedin',ID,'Fixture','Fixture job','India','https://www.linkedin.com/jobs/view/'+ID+'/','')
        result=prepare_portal_job(self.page,job,FACTS,resume_path=self.resume)
        self.assertEqual(result.reason,'already_applied_on_portal')
        self.assertTrue(result.exact_job_verified)
        self.assertFalse(result.form_exercised)
        self.assertEqual(self.page.evaluate('window.clicks'),0)


if __name__=='__main__':unittest.main()
