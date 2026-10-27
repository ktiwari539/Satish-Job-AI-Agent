"""Real Chromium on synthetic auth/JD pages; no real credentials or mailbox."""
import json
import os
import sys
import unittest
import tempfile
from types import SimpleNamespace
from urllib.parse import urlsplit
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from auth_bridge import AccountSecret
from portal_session import ensure_portal_session
from verified_jd import read_verified_job_description
from models import Job
from certify_portals import run_on_page
from resume_store import import_resume
from store import JobStore
from test_multi_portal_fixtures import FACTS,PUBLIC

ROOT=Path(__file__).resolve().parents[2]
JD='Customer success onboarding stakeholder management retention SLA enterprise clients. '*5


def login_html(portal, *, otp=False, staged=False, action=''):
    url={'linkedin':'/feed/','naukri':'/mnjuser/profile','indeed':'/jobs'}[portal]
    action=action or {'linkedin':'https://www.linkedin.com/login','naukri':'https://www.naukri.com/nlogin/login','indeed':'https://secure.indeed.com/account/login'}[portal]
    return '''<main id="root"></main><script>
    window.passwordSubmits=0; window.codeSubmits=0; window.loginClicks=0;
    const root=document.querySelector('#root');
    function done(){history.pushState({},'',URL);root.innerHTML='<nav>My profile Logout Jobs My Network Messaging Resume headline Key skills</nav>';}
    function challenge(){root.innerHTML='<h1>Sign in: check your email for a verification code</h1><form method="post" action="ACTION"><input name="otp" autocomplete="one-time-code"><button type="submit">Verify</button></form>';root.querySelector('form').onsubmit=e=>{e.preventDefault();window.codeSubmits++;if(root.querySelector('input').value==='123456')done();};}
    function render(passwordOnly){root.innerHTML='<h1>Sign in</h1><form method="post" action="ACTION">'+(!passwordOnly?'<input type="email" name="email">':'')+(passwordOnly||!STAGED?'<input type="password" name="password">':'')+'<button type="submit">Continue</button></form>';root.querySelector('form').onsubmit=e=>{e.preventDefault();window.loginClicks++;if(!root.querySelector('input[type="password"]')){render(true);return;}window.passwordSubmits++;if(OTP)challenge();else done();};}
    render(false);</script>'''.replace('URL',json.dumps(url)).replace('ACTION',action).replace('STAGED',str(staged).lower()).replace('OTP',str(otp).lower())


class AuthJDFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.pw=sync_playwright().start(); cls.browser=cls.pw.chromium.launch(headless=True)
        except Exception:
            if os.environ.get('REQUIRE_BROWSER_FIXTURES')=='1': raise
            raise unittest.SkipTest('Browser fixtures unavailable')

    @classmethod
    def tearDownClass(cls): cls.browser.close(); cls.pw.stop()

    def setUp(self):
        self.context=self.browser.new_context(); self.addCleanup(self.context.close)
        self.page=self.context.new_page(); self.page.set_default_timeout(1200)
        self.provider=Mock()
        self.provider.credentials.return_value=AccountSecret('fixture@example.invalid','fixture-pass')
        self.provider.email_otp.return_value='123456'

    def route(self,html,url='https://www.linkedin.com/login'):
        self.context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=html))
        self.page.goto(url)

    def test_three_portals_sign_in_once_then_verify_positive_session(self):
        for portal,url in (('linkedin','https://www.linkedin.com/login'),('naukri','https://www.naukri.com/nlogin/login'),('indeed','https://secure.indeed.com/account/login')):
            with self.subTest(portal=portal):
                self.context.unroute('**/*'); self.route(login_html(portal),url)
                result=ensure_portal_session(self.page,portal,self.provider)
                self.assertTrue(result.authenticated,result)
                self.assertEqual(self.page.evaluate('window.passwordSubmits'),1)

    def test_indeed_native_email_then_password_steps_are_bounded(self):
        self.route(login_html('indeed',staged=True),'https://secure.indeed.com/account/login')
        result=ensure_portal_session(self.page,'indeed',self.provider)
        self.assertTrue(result.authenticated,result)
        self.assertEqual(self.page.evaluate('window.loginClicks'),2)
        self.assertEqual(result.login_attempts,1)

    def test_fresh_email_bridge_code_is_used_once_and_session_rechecked(self):
        self.route(login_html('linkedin',otp=True))
        result=ensure_portal_session(self.page,'linkedin',self.provider)
        self.assertTrue(result.authenticated,result)
        self.assertEqual(result.verification_source,'email_bridge')
        self.assertEqual(self.page.evaluate('window.codeSubmits'),1)
        self.provider.email_otp.assert_called_once()

    def test_manual_code_fallback_is_hidden_by_terminal_callback_and_not_reported(self):
        self.route(login_html('linkedin',otp=True)); prompt=Mock(return_value='123456')
        result=ensure_portal_session(self.page,'linkedin',self.provider,otp_mode='manual',prompt=prompt)
        self.assertTrue(result.authenticated,result)
        self.assertNotIn('123456',str(result)); prompt.assert_called_once_with('linkedin')
        self.provider.email_otp.assert_not_called()

    def test_wrong_code_has_no_retry_and_never_claims_authentication(self):
        self.route(login_html('linkedin',otp=True)); self.provider.email_otp.return_value='654321'
        result=ensure_portal_session(self.page,'linkedin',self.provider)
        self.assertFalse(result.authenticated)
        self.assertEqual(self.page.evaluate('window.codeSubmits'),1)
        self.provider.email_otp.assert_called_once()

    def test_captcha_never_requests_credentials_or_mail(self):
        self.route('<h1>Verify you are human CAPTCHA</h1>')
        result=ensure_portal_session(self.page,'linkedin',self.provider)
        self.assertEqual(result.state,'HUMAN_ACTION_REQUIRED')
        self.provider.credentials.assert_not_called(); self.provider.email_otp.assert_not_called()

    def test_preexisting_checkpoint_is_preserved_without_another_password_attempt(self):
        self.route('<h1>Check your email for verification</h1><form method="post"><input autocomplete="one-time-code"><button type="submit">Verify</button></form>',
                   'https://www.linkedin.com/checkpoint/challenge/fixture')
        result=ensure_portal_session(self.page,'linkedin',self.provider)
        self.assertFalse(result.authenticated)
        self.assertEqual(result.reason,'existing_login_challenge_requires_human')
        self.assertIn('/checkpoint/challenge/',self.page.url)
        self.provider.credentials.assert_not_called(); self.provider.email_otp.assert_not_called()

    def test_foreign_form_action_never_receives_secrets(self):
        self.route(login_html('linkedin',action='https://evil.invalid/login'))
        result=ensure_portal_session(self.page,'linkedin',self.provider)
        self.assertFalse(result.authenticated)
        self.assertEqual(self.page.locator('input[type=password]').input_value(),'')
        self.assertEqual(self.page.evaluate('window.loginClicks'),0)

    def test_javascript_login_without_native_post_verifies_session(self):
        html=login_html('naukri').replace('method="post" action="https://www.naukri.com/nlogin/login"','')
        self.route(html,'https://www.naukri.com/nlogin/login')
        result=ensure_portal_session(self.page,'naukri',self.provider)
        self.assertTrue(result.authenticated,result)
        self.assertEqual(self.page.evaluate('window.passwordSubmits'),1)

    def test_default_get_form_cannot_put_credentials_in_a_url(self):
        self.route('<h1>Sign in</h1><form><input type="email"><input type="password"><button type="submit">Sign in</button></form>')
        result=ensure_portal_session(self.page,'linkedin',self.provider,otp_mode='none')
        self.assertFalse(result.authenticated)
        self.assertNotIn('fixture-pass',self.page.url)
        self.assertNotIn('fixture%40',self.page.url)

    def test_delayed_public_layout_after_short_placeholder_enriches_exact_job(self):
        url='https://www.linkedin.com/jobs/view/9000000001/'
        self.route('<main><div class="jobs-description__content">About the job</div><div id="later"></div></main><script>setTimeout(()=>document.querySelector("#later").innerHTML='+json.dumps('<section class="show-more-less-html__markup">'+JD+'</section>')+',1800);</script>',url)
        job=Job('linkedin','9000000001','Fixture','Customer Success Manager','India',url,'')
        result,evidence=read_verified_job_description(self.page,job,('customer success',))
        self.assertTrue(result.enriched,evidence)
        self.assertGreater(evidence['probes'],3)
        self.assertEqual(evidence['read_route'],'visible_scoped')

    def test_jsonld_only_correct_job_is_accepted_but_recommendation_is_rejected(self):
        url='https://www.linkedin.com/jobs/view/9000000001/'
        job=Job('linkedin','9000000001','Fixture','Customer Success Manager','India',url,'')
        for jid,expected in (('9000000001',True),('9000000002',False)):
            node={'@type':'JobPosting','url':'https://www.linkedin.com/jobs/view/'+jid+'/', 'title':job.title,
                  'hiringOrganization':{'name':'Fixture'},'jobLocation':{'address':{'addressCountry':'India'}},'description':JD}
            self.context.unroute('**/*'); self.route('<main>No visible job description</main><script type="application/ld+json">'+json.dumps(node)+'</script>',url)
            result,evidence=read_verified_job_description(self.page,job,(),max_probes=1)
            self.assertEqual(result.enriched,expected,evidence)
            if expected: self.assertEqual(evidence['read_route'],'exact_job_structured')

    def test_missing_layout_is_classified_with_structure_without_page_text(self):
        url='https://www.linkedin.com/jobs/view/9000000001/'
        self.route('<main><h1>Fixture unknown layout</h1>private@example.invalid</main>',url)
        result,evidence=read_verified_job_description(self.page,Job('linkedin','9000000001','Fixture','Role','India',url,''),(),max_probes=1)
        self.assertEqual(result.reason,'jd_missing_selector_layout')
        self.assertNotIn('private@example.invalid',json.dumps(evidence))
        self.assertTrue(evidence['selectors'])

    def test_hidden_login_inputs_and_recaptcha_branding_are_not_a_login_challenge(self):
        url='https://www.linkedin.com/jobs/view/9000000001/'
        self.route('<main><section class="jobs-description__content">'+JD+'</section><footer>Protected by reCAPTCHA</footer><form style="display:none" action="/login"><input type="password"></form></main>',url)
        job=Job('linkedin','9000000001','Fixture','Role','India',url,'')
        result,evidence=read_verified_job_description(self.page,job,(),max_probes=1)
        self.assertTrue(result.enriched,evidence)

    def test_runner_signs_in_skips_missing_jd_and_prepares_the_next_job(self):
        first='https://www.naukri.com/job-listings-fixture-9000000001'
        second='https://www.naukri.com/job-listings-fixture-9000000002'
        native=(ROOT/'tests/fixtures/native_application.html').read_text()
        signin=login_html('naukri').replace("function done(){", "function done(){document.cookie='fixture_session=1; path=/';")
        def respond(route):
            path=urlsplit(route.request.url).path
            if path=='/mnjuser/profile':
                html='<nav>Logout View profile Resume headline Key skills</nav>' if 'fixture_session=1' in route.request.headers.get('cookie','') else signin
            elif '/nlogin/' in path: html=signin
            elif path.endswith('9000000001'): html='<main>Unknown layout with no job description</main>'
            elif path.endswith('9000000002'): html=native
            else:
                html=''.join('<article class="jobTuple"><a class="title" href="'+url+'">Customer Success Manager</a><a class="comp-name">Fixture Employer '+str(i)+'</a><span class="location">India</span><span data-job-id="900000000'+str(i)+'"></span></article>' for i,url in ((1,first),(2,second)))
            route.fulfill(status=200,content_type='text/html',body=html)
        self.context.route('**/*',respond)
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'fixture_resume.pdf';source.write_bytes(b'%PDF fixture only')
            resume=str(import_resume(str(source),str(Path(directory)/'vault')))
            args=SimpleNamespace(portals=('naukri',),sources='',max_jobs=10,query='Customer Success Manager',location='India',threshold=75,resume_path=resume,otp_mode='auto')
            report=run_on_page(self.page,args,PUBLIC,FACTS,JobStore(str(Path(directory)/'jobs.db')),auth_provider=self.provider)
        self.assertEqual(report['preparation']['skipped_jd'],1,report)
        self.assertEqual(report['preparation']['ready_for_review'],1,report)
        self.assertTrue(report['portal_results'][0]['authentication']['authenticated'])
        self.assertEqual(len(report['jd_evidence']),2)
        self.assertEqual(report['submitted'],0)
        self.assertEqual(self.page.evaluate('window.submitClicks'),0)
        self.provider.credentials.assert_called_once_with('naukri')
        report['verification_scope']='synthetic_login_jd_recovery_and_review_only_NOT_live_portal_acceptance'
        report['browser_version']=self.browser.version
        artifact=ROOT/'data/auth_jd_fixture_acceptance.json'
        artifact.parent.mkdir(parents=True,exist_ok=True)
        artifact.write_text(json.dumps(report,indent=2,sort_keys=True))
