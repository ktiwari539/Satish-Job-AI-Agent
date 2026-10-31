"""Synthetic Chromium: verified answer formats, rejection, and private learning."""
from contextlib import redirect_stdout
import io,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from application_forms import FillPlan
from browser_form_runtime import apply_fill_plan,build_page_fill_plan
from linkedin_application import run_linkedin_application
from models import Job
from portal_preparation import prepare_portal_job
from question_requests import record_pending_questions,review_pending_questions
from resume_store import import_resume

URL='https://www.linkedin.com/jobs/view/9400000001/'
FACTS=dict(full_name='Fixture Applicant',email='fixture@example.invalid',phone='2025550123',location='Fixture City',
           current_ctc_inr='1250000',notice_period_days='30',customer_success_years='7',
           answers={'Are you willing to relocate?':'Yes'})


class AnswerRecoveryFixtures(unittest.TestCase):
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
        self.root=Path(self.folder.name)
        file=self.root/'fixture_resume.pdf';file.write_bytes(b'%PDF-1.4 fixture only')
        self.resume=import_resume(str(file),str(self.root/'vault'))
        self.wizard=(ROOT/'tests/fixtures/linkedin_wizard.html').read_text()
    def load(self,html):
        self.context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=html))
        self.page.goto(URL)
    def run_form(self):
        return run_linkedin_application(self.page,dict(FACTS),open_easy_apply=True,fill_application=True,
                    advance_application=True,inspect_review=True,resume_path=str(self.resume),live_submission_enabled=False)

    def test_verified_unit_and_wording_variants_reach_review(self):
        extra='<label for="ctc">Please specify your present annual compensation in LPA *</label><input id="ctc" required type="number" step="0.1"><label for="notice">Notice period in days *</label><input id="notice" required type="number"><label for="years">Customer Success Experience (years) *</label><input id="years" required type="number">'
        html=self.wizard.replace('<button onclick="go(4)">Review</button>',extra+'<button onclick="go(4)">Review</button>')
        html=html.replace('function go(n) {','function go(n) { if(n===4) window.answers=["ctc","notice","years"].map(id=>document.getElementById(id).value);')
        self.load(html);run=self.run_form()
        self.assertEqual(run.flow.state,'REVIEW_INSPECTED',run.flow)
        self.assertEqual(self.page.evaluate('window.answers'),['12.5','30','7'])
        self.assertEqual(self.page.evaluate('window.submitClicks'),0)
        evidence=dict(verification_scope='synthetic_chromium_answer_formats_to_review_not_live_linkedin',
            unit_form_fields_verified=3,review_inspected=True,submitted=0,submit_clicks=0,
            fact_sources='explicit_fixture_profile',unknown_facts_invented=0)
        (ROOT/'data/answer_recovery_fixture_acceptance.json').write_text(json.dumps(evidence,indent=2)+'\n')

    def test_lost_text_value_is_repaired_once_before_navigation(self):
        html=self.wizard.replace('id="email" required','id="email" required oninput="window.fills=(window.fills||0)+1;if(window.fills===1)this.value=\'\'"')
        self.load(html);run=self.run_form()
        self.assertEqual(run.flow.state,'REVIEW_INSPECTED',run.flow)
        self.assertEqual(self.page.evaluate('window.fills'),2)
        self.assertEqual(self.page.evaluate('window.submitClicks'),0)

    def test_rejected_verified_value_stops_after_one_retry_without_next(self):
        html=self.wizard.replace('id="email" required','id="email" required aria-invalid="true" oninput="window.fills=(window.fills||0)+1"')
        self.load(html)
        with patch('browser_form_runtime.trace_event') as trace:run=self.run_form()
        self.assertEqual(run.flow.state,'BLOCKED_AFTER_FILL')
        self.assertEqual(self.page.evaluate('window.step'),1)
        self.assertEqual(self.page.evaluate('window.fills'),2)
        self.assertEqual(self.page.locator('#email').input_value(),FACTS['email'])
        self.assertNotIn(FACTS['email'],str(trace.call_args_list))
        self.assertEqual(self.page.evaluate('window.submitClicks'),0)

    def test_numeric_constraints_never_inflate_experience_or_clamp_values(self):
        self.load('<div role="dialog"><label for="years">Customer success experience (years) *</label><input id="years" type="number" min="8" required></div>')
        plan=build_page_fill_plan(self.page,dict(FACTS))
        failures=apply_fill_plan(self.page,plan,verify_readback=True)
        self.assertTrue(any(r.startswith('field_value_unverified:') for r in failures))
        self.assertEqual(self.page.locator('#years').input_value(),'7')

    def test_opaque_select_values_keep_verified_option_labels(self):
        self.load('<div role="dialog"><label for="ctc">Current CTC (LPA) *</label><select id="ctc" required><option value="">Select</option><option value="opaque-a">12.5 LPA</option><option value="opaque-b">20 LPA</option></select></div>')
        plan=build_page_fill_plan(self.page,dict(FACTS))
        self.assertEqual(plan.values['ctc'],'12.5 LPA')
        failures=apply_fill_plan(self.page,plan,verify_readback=True)
        self.assertFalse(any(r.startswith('field_') for r in failures),failures)
        self.assertEqual(self.page.locator('#ctc').input_value(),'opaque-a')

    def test_numeric_readback_accepts_equivalent_formatting_without_rounding(self):
        self.load('<div role="dialog"><input id="years" type="number" oninput="this.value=this.value.replace(/\\.0+$/,\'\')"></div>')
        failures=apply_fill_plan(self.page,FillPlan(values={'years':'7.00'},can_fill=True),verify_readback=True)
        self.assertEqual(failures,())
        self.assertEqual(self.page.locator('#years').input_value(),'7')

    def test_same_input_key_on_a_new_question_never_receives_a_stale_retry(self):
        self.load('<div role="dialog"><label id="prompt" for="q">Customer success experience (years)</label><input id="q" oninput="window.fills=(window.fills||0)+1;document.getElementById(\'prompt\').textContent=\'Do you hold the employer certificate?\';this.value=\'\'"></div>')
        failures=apply_fill_plan(self.page,FillPlan(values={'q':'7'},can_fill=True),verify_readback=True)
        self.assertTrue(any(r.startswith('field_value_unverified:') for r in failures))
        self.assertEqual(self.page.evaluate('window.fills'),1)
        self.assertEqual(self.page.locator('#q').input_value(),'')

    def test_actual_unknown_is_saved_privately_reviewed_once_then_reaches_review(self):
        html=self.wizard.replace("const unknown = new URLSearchParams(location.search).has('unknown');",'const unknown = true;')
        self.load(html)
        job=Job('linkedin','9400000001','Fixture','Customer Success Manager','India',URL,'')
        path=self.root/'questions.json';profile_path=self.root/'private.json'
        profile_path.write_text(json.dumps(FACTS))
        def capture(*args,**kwargs):return record_pending_questions(*args,**kwargs,path=path)
        with patch('question_requests.record_pending_questions',side_effect=capture):
            blocked=prepare_portal_job(self.page,job,dict(FACTS),resume_path=str(self.resume))
        self.assertEqual(blocked.flow_state,'BLOCKED_UNKNOWN_REQUIRED_FIELDS')
        self.assertFalse(blocked.review_exercised)
        self.assertEqual(blocked.review_mismatch_count,0)
        self.assertEqual(blocked.resume_evidence_state,'not_checked')
        self.assertEqual(blocked.pending_questions_report,str(path))
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertNotIn(FACTS['email'],path.read_text())
        with patch('builtins.input',return_value='No'),redirect_stdout(io.StringIO()):
            learned=review_pending_questions(profile_path,path=path)
        self.assertEqual(learned['answers_saved'],1)
        ready=prepare_portal_job(self.page,job,json.loads(profile_path.read_text()),resume_path=str(self.resume))
        self.assertEqual(ready.state,'READY_FOR_REVIEW',ready)
        self.assertTrue(ready.review_exercised and ready.identity_verified)
        self.assertEqual(ready.resume_evidence_state,'matching_resume_selected')
        self.assertEqual(self.page.evaluate('window.submitClicks'),0)


if __name__=='__main__':unittest.main()
