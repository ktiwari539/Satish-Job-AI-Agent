"""Synthetic Chromium evidence, not certification of real portal accounts."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from models import CandidateProfile, Job
from resume_store import import_resume
from portal_preparation import prepare_portal_job
from certify_portals import run_on_page
from browser_qa import extract_current_jobs
from jd_enrichment import _read_first_visible
from store import JobStore

FACTS=dict(full_name='Fixture Applicant',email='fixture@example.invalid',phone='2025550123',location='Fixture City',
           answers={'Are you willing to relocate?':'Yes'})
PUBLIC=CandidateProfile.from_dict(dict(target_roles=['customer success manager'],skills=['customer success','onboarding','sla'],
    preferred_locations=['india'],remote_allowed=True,total_experience_years=8,india_authorized=True,outside_india_sponsorship_required=True))


class MultiPortalFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.pw=sync_playwright().start()
            cls.browser=cls.pw.chromium.launch(headless=True)
        except Exception:
            if os.environ.get('REQUIRE_BROWSER_FIXTURES')=='1': raise
            raise unittest.SkipTest('Install browser fixture requirements and Chromium')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop()

    def setUp(self):
        self.context=self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page=self.context.new_page()
        self.page.set_default_timeout(1500)
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        source=Path(self.folder.name)/'fixture_resume.pdf'
        source.write_bytes(b'%PDF synthetic only')
        self.resume=str(import_resume(str(source),str(Path(self.folder.name)/'vault')))
        self.native=(ROOT/'tests/fixtures/native_application.html').read_text()

    def test_native_forms_across_four_sources_have_shared_cross_checks_and_zero_submits(self):
        cases=[('naukri','9001','https://www.naukri.com/job-listings-fixture-9001'),
               ('indeed','abc123','https://in.indeed.com/viewjob?jk=abc123'),
               ('greenhouse','9001','https://boards.greenhouse.io/fixture/jobs/9001'),
               ('lever','9001','https://jobs.lever.co/fixture/9001')]
        for portal,jid,url in cases:
            with self.subTest(portal=portal):
                self.context.route('**/*',lambda route: route.fulfill(status=200,content_type='text/html',body=self.native))
                result=prepare_portal_job(self.page,Job(portal,jid,'Fixture','Customer Success Manager','India',url,''),FACTS,resume_path=self.resume)
                self.assertEqual(result.state,'READY_FOR_REVIEW',result)
                self.assertTrue(result.exact_job_verified and result.identity_verified and result.submit_control_verified)
                self.assertEqual(result.resume_evidence_state,'matching_resume_selected')
                self.assertEqual(self.page.evaluate('window.submitClicks'),0)
                self.context.unroute('**/*')

    def test_one_click_apply_is_not_clicked_as_navigation(self):
        html='<main><h1>Customer Success Manager</h1><button onclick="window.submitClicks++">Apply</button></main><script>window.submitClicks=0</script>'
        self.context.route('**/*',lambda route: route.fulfill(status=200,content_type='text/html',body=html))
        job=Job('naukri','9001','Fixture','Customer Success Manager','India','https://www.naukri.com/job-listings-fixture-9001','')
        result=prepare_portal_job(self.page,job,FACTS,resume_path=self.resume)
        self.assertEqual(result.reason,'application_entry_requires_portal_adapter')
        self.assertEqual(self.page.evaluate('window.submitClicks'),0)

    def test_unknown_native_answer_blocks_without_fabrication(self):
        self.context.route('**/*',lambda route: route.fulfill(status=200,content_type='text/html',body=self.native))
        job=Job('indeed','abc123','Fixture','Customer Success Manager','India','https://in.indeed.com/viewjob?jk=abc123&unknown=1','')
        result=prepare_portal_job(self.page,job,FACTS,resume_path=self.resume)
        self.assertEqual(result.state,'BLOCKED')
        self.assertGreater(result.unknown_required_count,0)
        self.assertEqual(self.page.locator('#certificate').input_value(),'')
        self.assertEqual(self.page.evaluate('window.submitClicks'),0)

    def test_hidden_or_stale_description_cannot_override_visible_job_details(self):
        self.page.set_content('<section id="jobDescriptionText" style="display:none">Wrong hidden job description</section><section id="jobDescriptionText">Current visible job description</section>')
        self.assertEqual(_read_first_visible(self.page,('#jobDescriptionText',)), 'Current visible job description')

    def test_real_three_portal_discovery_qualification_dedupe_and_block_recovery(self):
        linked='https://www.linkedin.com/jobs/view/9100000003/'
        naukri='https://www.naukri.com/job-listings-fixture-9100000004?unknown=1'
        indeed_duplicate='https://in.indeed.com/viewjob?jk=duplicate'
        indeed_ready='https://in.indeed.com/viewjob?jk=ready123'
        counts=[]
        wizard=(ROOT/'tests/fixtures/linkedin_wizard.html').read_text().replace('<main>', '<main><section class="jobs-description__content">Customer success onboarding SLA stakeholder management retention. We seek a Customer Success Manager in India with minimum 5 years of experience. Own customer success, onboarding, SLA reporting and stakeholder management for enterprise clients.</section>',1)
        def indeed_card(url,company):
            return '<div class="job_seen_beacon"><h2 class="jobTitle"><a href="'+url+'">Customer Success Manager</a></h2><span data-testid="company-name">'+company+'</span><span data-testid="text-location">India</span></div>'
        def respond(route):
            url=route.request.url; parsed=urlsplit(url); query=parse_qs(parsed.query)
            if parsed.hostname=='www.linkedin.com' and '/feed/' in parsed.path:
                html='<nav>Jobs My Network Messaging</nav>'
            elif parsed.hostname=='www.linkedin.com' and '/jobs/search/' in parsed.path:
                html='<li class="scaffold-layout__list-item"><a class="job-card-list__title--link" href="'+linked+'">Customer Success Manager</a><span class="artdeco-entity-lockup__subtitle">Shared Fixture Employer</span><span class="artdeco-entity-lockup__caption">India</span></li>'
            elif parsed.hostname=='www.naukri.com' and '/mnjuser/profile' in parsed.path:
                html='<main>Resume headline Key skills</main>'
            elif parsed.hostname=='www.naukri.com' and not parsed.path.startswith('/job-listings-'):
                html='<article class="jobTuple"><a class="title" href="'+naukri+'">Customer Success Manager</a><a class="comp-name">Naukri Fixture Employer</a><span class="location">India</span><span data-job-id="9100000004"></span></article>'
            elif parsed.hostname=='in.indeed.com' and parsed.path=='/jobs' and 'q' not in query:
                html='<nav>My profile Sign out</nav>'
            elif parsed.hostname=='in.indeed.com' and parsed.path=='/jobs':
                html=indeed_card(indeed_duplicate,'Shared Fixture Employer')+indeed_card(indeed_ready,'Indeed Fixture Employer')
            elif parsed.hostname=='www.linkedin.com': html=wizard
            else:
                html=self.native
                if parsed.hostname == 'www.naukri.com':
                    html=html.replace("if(new URLSearchParams(location.search).has('unknown'))", 'if(true)')
            route.fulfill(status=200,content_type='text/html',body=html)
        self.context.route('**/*',respond)
        self.page.on('framenavigated', lambda frame: counts.append(frame.url) if frame==self.page.main_frame else None)
        args=SimpleNamespace(portals=('linkedin','naukri','indeed'),query='Customer Success Manager',location='India',
            max_jobs=10,sources='',threshold=75,resume_path=self.resume)
        report=run_on_page(self.page,args,PUBLIC,FACTS,JobStore(str(Path(self.folder.name)/'jobs.db')))
        batch=report['preparation']
        self.assertEqual(batch['discovered'],4,report)
        self.assertEqual(batch['ready_for_review'],2,report)
        self.assertEqual(batch['blocked'],1,report)
        self.assertEqual(batch['skipped_duplicate'],1,report)
        self.assertEqual([x['source'] for x in report['application_evidence']],['linkedin','naukri','indeed'])
        self.assertEqual(report['submitted'],0)
        self.assertFalse(report['live_portal_certification'])
        self.assertEqual(self.page.evaluate('window.submitClicks'),0)
        report['verification_scope']='synthetic_Chromium_fixtures_only_NOT_live_portal_certification'
        report['browser_version']=self.browser.version
        artifact=ROOT/'data/multi_portal_fixture_acceptance.json'
        artifact.parent.mkdir(parents=True,exist_ok=True)
        artifact.write_text(json.dumps(report,indent=2,sort_keys=True))
