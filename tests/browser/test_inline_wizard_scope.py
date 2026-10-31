"""ZIP-guided role-less wizard regressions; synthetic DOM, no live portals."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from application_flow import _visible_action,_validated_required_wizard_fields
from linkedin_application import run_linkedin_application
from resume_evidence import inspect_resume_evidence
from resume_store import import_resume
from screening_groups import answer_verified_screening_groups,inspect_screening_groups
from wizard_dom import mark_active_wizard


class InlineWizardScope(unittest.TestCase):
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
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        original=Path(self.folder.name)/'fixture_resume.pdf';original.write_bytes(b'%PDF-1.4 fixture')
        self.resume=import_resume(str(original),str(Path(self.folder.name)/'vault'))
    def load(self,html):
        self.context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=html))
        self.page.goto('https://www.linkedin.com/jobs/view/9700000001/')
    def group(self,number):
        return ('<div><label class="fixture-question-label">Do you hold fixture qualification '+str(number)+'? *</label>'
            '<div class="options"><label><input required type="radio" name="q'+str(number)+'">Yes</label>'
            '<label><input required type="radio" name="q'+str(number)+'">No</label></div></div>')

    def test_decorated_counter_long_review_action_and_three_sibling_prompts(self):
        self.load('<main><aside>'+'fixture context '*1000+'</aside><article>'+''.join(self.group(i) for i in range(3))+
            '<footer><span>Progress 3/4 pages • 75%</span><button aria-label="Review your application">Review your application</button></footer></article></main>')
        groups=inspect_screening_groups(self.page)
        self.assertEqual(len(groups),3,groups)
        profile={'answers':{'Do you hold fixture qualification '+str(i)+'?':('Yes' if i==1 else 'No') for i in range(3)}}
        result=answer_verified_screening_groups(self.page,profile)
        self.assertEqual(result.choices_confirmed,3,result)
        self.assertTrue(_validated_required_wizard_fields(self.page))

    def test_question_label_above_option_container_is_not_lost(self):
        self.load('<article>'+self.group(1)+'<p>3/5 pages</p><button>Next</button></article>')
        groups=inspect_screening_groups(self.page)
        self.assertEqual(len(groups),1)
        self.assertEqual(groups[0]['question'],'Do you hold fixture qualification 1? *')
        self.assertEqual(groups[0]['options'],('Yes','No'))

    def test_final_review_footer_does_not_hide_the_resume_card(self):
        html='<aside><a>unrelated_fixture.pdf</a></aside><article><h2>Review your application</h2><p>'+('fixture context '*800)+'</p><div><p>Resume</p><a>fixture_resume.pdf</a></div><footer><span>4/4 pages • complete</span><button>Submit application</button></footer></article>'
        self.load(html)
        self.assertGreater(len(self.page.locator('article').inner_text()),9000)
        self.assertEqual(inspect_resume_evidence(self.page,str(self.resume)),'matching_resume_selected')
        self.page.locator('article a').evaluate("el=>el.textContent='other_fixture.pdf'")
        self.assertEqual(inspect_resume_evidence(self.page,str(self.resume)),'different_resume_selected')

    def test_saved_file_listing_is_not_selected_attachment_evidence(self):
        self.load('<article><p>Resume</p><a>fixture_resume.pdf</a><p>2/4 pages</p><button>Next</button></article>')
        self.assertNotEqual(inspect_resume_evidence(self.page,str(self.resume)),'matching_resume_selected')

    def test_one_active_wizard_scopes_two_visible_next_buttons_and_reaches_review(self):
        html=(ROOT/'tests/fixtures/linkedin_wizard.html').read_text()
        html=html.replace('<main>','<button onclick="window.backgroundClicks++">Next</button><main>')
        html=html.replace('window.submitClicks = 0;','window.backgroundClicks=0; window.submitClicks = 0;')
        html=html.replace('<p>${n}/4 pages</p>','<p>Progress ${n}/4 pages • status</p>')
        html=html.replace('<h2>Review your application</h2>','<h2>Review your application</h2><p>'+('fixture context '*800)+'</p>')
        salary='<label for="pay">What’s your current salary? (in lakhs per annum)</label><input id="pay" required type="number" step="0.1"><label for="years">How many years of work experience do you have with Fixture Industry?</label><input id="years" required inputmode="numeric" pattern="[0-9]+">'
        html=html.replace('<button onclick="go(4)">Review</button>',salary+'<button aria-label="Review your application" onclick="go(4)">Review your application</button>')
        html=html.replace('function go(n) {','function go(n) { if(n===4){window.salaryValue=document.getElementById("pay").value;window.yearsValue=document.getElementById("years").value;}')
        self.context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=html))
        self.page.goto('https://www.linkedin.com/jobs/view/9700000001/?layout=inline')
        profile=dict(full_name='Fixture Applicant',email='fixture@example.invalid',phone='2025550123',location='Fixture City',current_ctc_inr='1340000',answers={'Are you willing to relocate?':'Yes','How many years of work experience do you have with Fixture Industry?':'NA - 0'})
        run=run_linkedin_application(self.page,profile,open_easy_apply=True,fill_application=True,advance_application=True,inspect_review=True,resume_path=str(self.resume),live_submission_enabled=False)
        self.assertEqual(run.flow.state,'REVIEW_INSPECTED',run.flow)
        self.assertEqual(self.page.evaluate('window.salaryValue'),'13.4')
        self.assertEqual(self.page.evaluate('window.yearsValue'),'0')
        self.assertEqual(inspect_resume_evidence(self.page,str(self.resume)),'matching_resume_selected')
        self.assertEqual(self.page.evaluate('window.backgroundClicks'),0)
        self.assertEqual(self.page.evaluate('window.submitClicks'),0)
        target=ROOT/'data/inline_scope_fixture_acceptance.json';target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(dict(verification_scope='zip_guided_synthetic_inline_wizard_not_live_linkedin',decorated_counter_to_review=True,background_next_clicks=0,configured_resume_verified=True,salary_lpa_numeric_verified=True,submitted=0),indent=2)+'\n')

    def test_independent_wizards_are_ambiguous_and_unknown_fact_is_not_guessed(self):
        self.load(''.join('<article>'+self.group(i)+'<p>3/4 pages</p><button>Review your application</button></article>' for i in range(2)))
        self.assertEqual(mark_active_wizard(self.page),'missing')
        self.assertIsNone(_visible_action(self.page,('Review your application',))[0])
        self.assertEqual(answer_verified_screening_groups(self.page,{}).choices_confirmed,0)
        self.page.locator('article').last.evaluate('(el)=>el.remove()')
        result=answer_verified_screening_groups(self.page,{})
        self.assertEqual(len(result.unresolved_questions),1,result)
        self.assertEqual(self.page.locator('input:checked').count(),0)
