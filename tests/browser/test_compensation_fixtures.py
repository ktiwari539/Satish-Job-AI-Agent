"""Synthetic Chromium salary validation and Review; no live applications."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from browser_form_runtime import apply_fill_plan,build_page_fill_plan
from linkedin_application import run_linkedin_application
from resume_store import import_resume

CURRENT='What is your current annual compensation?'
EXPECTED='Annual compensation expectation (INR)'


class CompensationFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(headless=True)
        except Exception:
            if os.environ.get('REQUIRE_BROWSER_FIXTURES')=='1':raise
            raise unittest.SkipTest('Install Playwright and Chromium')
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.context=self.browser.new_context();self.addCleanup(self.context.close)
        self.page=self.context.new_page();self.page.set_default_timeout(1500)

    def test_current_and_expected_numeric_values_reach_review_from_profile_and_controls(self):
        sources=(dict(current_ctc='13.4 LPA',expected_ctc='21.75 LPA'),
            {'_control_answer_bank':{CURRENT.lower().rstrip('?'):dict(approved=True,answer='13.4 LPA'),
                'expected ctc in lpa':dict(approved=True,answer='21.75')}})
        for source in sources:
            with self.subTest(source='controls' if '_control_answer_bank' in source else 'profile'),tempfile.TemporaryDirectory() as folder:
                file=Path(folder)/'fixture_resume.pdf';file.write_bytes(b'%PDF-1.4 fixture')
                resume=import_resume(str(file),str(Path(folder)/'vault'))
                fields='<label for="current">'+CURRENT+'</label><input required id="current" type="text" inputmode="numeric" pattern="[0-9]+" oninput="this.setCustomValidity(/^[0-9]+$/.test(this.value)?\'\':\'Enter numbers only\')"><label for="expected">'+EXPECTED+'</label><input required id="expected" type="number" step="1">'
                html=(ROOT/'tests/fixtures/linkedin_wizard.html').read_text().replace('<button onclick="go(4)">Review</button>',fields+'<button onclick="go(4)">Review</button>')
                html=html.replace('function go(n) {','function go(n) { if(n===4){if(!["current","expected"].every(id=>document.getElementById(id).checkValidity()))return;window.salaryValues=["current","expected"].map(id=>document.getElementById(id).value);}')
                self.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=html))
                self.page.goto('https://www.linkedin.com/jobs/view/9600000001/')
                profile=dict(full_name='Fixture Applicant',email='fixture@example.invalid',phone='2025550123',location='Fixture City',answers={'Are you willing to relocate?':'Yes'},**source)
                run=run_linkedin_application(self.page,profile,open_easy_apply=True,fill_application=True,advance_application=True,inspect_review=True,resume_path=str(resume),live_submission_enabled=False)
                self.assertEqual(run.flow.state,'REVIEW_INSPECTED',run.flow)
                self.assertEqual(self.page.evaluate('window.salaryValues'),['1340000','2175000'])
                self.assertEqual(self.page.evaluate('window.submitClicks'),0)
                self.context.unroute('**/*')
        artifact=ROOT/'data/compensation_fixture_acceptance.json';artifact.parent.mkdir(parents=True,exist_ok=True)
        artifact.write_text(json.dumps(dict(verification_scope='synthetic_chromium_compensation_not_live_linkedin',profile_and_control_to_review=True,plain_numeric_amounts_accepted=True,current_expected_kept_distinct=True,submitted=0,submit_clicks=0),indent=2)+'\n')

    def test_visible_lpa_overrides_amount_key_and_text_input_gets_decimal_only(self):
        self.page.set_content('<div role="dialog"><label for="a">Current annual CTC (LPA)</label><input id="a" name="currentSalary.amount" inputmode="decimal" required pattern="[0-9]+([.][0-9]+)?"></div>')
        plan=build_page_fill_plan(self.page,dict(current_ctc_inr='1340000'))
        self.assertEqual(plan.values,{'currentSalary.amount':'13.4'})
        self.assertEqual(apply_fill_plan(self.page,plan,verify_readback=True),plan.reasons)
        self.assertEqual(self.page.locator('#a').input_value(),'13.4')

    def test_invalid_employer_limit_stops_without_changing_the_fact(self):
        self.page.set_content('<div role="dialog"><label for="a">Expected annual compensation (INR)</label><input id="a" type="number" max="2000000" required><button onclick="window.clicks++">Next</button></div><script>window.clicks=0</script>')
        profile=dict(expected_ctc='21.75 LPA')
        plan=build_page_fill_plan(self.page,profile)
        self.assertEqual(plan.values,{'a':'2175000'})
        failures=apply_fill_plan(self.page,plan,verify_readback=True)
        self.assertTrue(any(reason.startswith('field_value_unverified:') for reason in failures),failures)
        self.assertEqual(self.page.locator('#a').input_value(),'2175000')
        self.assertEqual(profile['expected_ctc'],'21.75 LPA')
        self.assertEqual(self.page.evaluate('window.clicks'),0)

    def test_grouped_rupees_and_exact_saved_answer_are_numeric_before_typing(self):
        self.page.set_content('<div role="dialog"><label for="a">Current annual compensation (INR)</label><input id="a" required type="number"></div>')
        plan=build_page_fill_plan(self.page,dict(answers={'Current annual compensation (INR)':'Rs. 13,40,000'}))
        self.assertEqual(plan.values,{'a':'1340000'})
        self.assertEqual(apply_fill_plan(self.page,plan,verify_readback=True),plan.reasons)
        self.assertEqual(self.page.locator('#a').input_value(),'1340000')
