"""Synthetic Chromium regressions for native `on` values; no live portals."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from application_flow import _validated_required_wizard_fields
from browser_form_runtime import inspect_page_fields
from screening_groups import inspect_screening_groups,answer_verified_screening_groups
from answer_import import import_reviewed_answers
from linkedin_application import run_linkedin_application
from resume_store import import_resume

Q='Do you hold the fixture certificate?'


class NativeRadioRecovery(unittest.TestCase):
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
        self.page=self.context.new_page();self.page.set_default_timeout(1000)

    def form(self,markup,*,inline=False):
        wrap='class="jobs-easy-apply-content"' if inline else 'role="dialog"'
        self.page.set_content('<input required id="background"><main '+wrap+'><p>2/4 pages</p>'+markup+'<button>Next</button></main>')

    def test_native_default_values_use_visible_sibling_labels_and_verified_clicks(self):
        for answer in ('Yes','No'):
            with self.subTest(answer=answer):
                self.form('<fieldset><legend>'+Q+' *</legend><div><input type="radio" name="fixture" required><span>Yes</span></div><div><input type="radio" name="fixture" required><span>No</span></div></fieldset>')
                self.assertEqual(self.page.locator('input[name=fixture]').first.input_value(),'on')
                groups=inspect_screening_groups(self.page)
                self.assertEqual(groups[0]['options'],('Yes','No'))
                fields=inspect_page_fields(self.page)
                self.assertTrue(all('on' not in f.options for f in fields))
                result=answer_verified_screening_groups(self.page,{'answers':{Q:answer}})
                self.assertEqual(result.choices_confirmed,1,result)
                self.assertEqual(self.page.locator('input[name=fixture]').nth(0 if answer=='Yes' else 1).is_checked(),True)
                self.assertTrue(_validated_required_wizard_fields(self.page))

    def test_hidden_native_controls_can_click_the_visible_single_option_wrapper(self):
        self.form('<fieldset><legend>'+Q+' *</legend><div onclick="this.querySelector(\'input\').click()"><input hidden type="radio" name="fixture" required><span>Yes</span></div><div onclick="this.querySelector(\'input\').click()"><input hidden type="radio" name="fixture" required><span>No</span></div></fieldset>')
        result=answer_verified_screening_groups(self.page,{'answers':{Q:'No'}})
        self.assertEqual(result.choices_confirmed,1,result)

    def test_named_group_common_ancestor_and_multiple_inline_sections(self):
        markup='<section class="jobs-easy-apply-form-section"><label>Unrelated</label><input></section>'
        for index in range(2):
            question='Do you have fixture qualification '+str(index)+'?'
            markup+='<section class="jobs-easy-apply-form-section"><h3>'+question+'</h3><div><input type="radio" name="q'+str(index)+'" required><span>Yes</span></div><div><input type="radio" name="q'+str(index)+'" required><span>No</span></div></section>'
        self.form(markup,inline=True)
        self.assertEqual(len(inspect_screening_groups(self.page)),2)
        profile={'answers':{'Do you have fixture qualification 0?':'No','Do you have fixture qualification 1?':'Yes'}}
        self.assertEqual(answer_verified_screening_groups(self.page,profile).choices_confirmed,2)
        self.assertTrue(_validated_required_wizard_fields(self.page))

    def test_default_or_numeric_values_without_visible_options_never_mean_yes(self):
        for values in ('','value="0"'):
            self.form('<fieldset><legend>'+Q+' *</legend><input type="radio" required name="fixture" '+values+'><input type="radio" name="fixture" required value="1"></fieldset>')
            self.assertEqual(inspect_screening_groups(self.page),())
            self.assertEqual(answer_verified_screening_groups(self.page,{'answers':{Q:'Yes'}}).choices_confirmed,0)
            self.assertFalse(self.page.locator('input[name=fixture]:checked').count())

    def test_shared_react_wrapper_does_not_reuse_the_first_question(self):
        markup='<div class="fb-dash-form-element">'
        for index in range(2):
            markup+='<section><h3>Do you hold fixture credential '+str(index)+'?</h3><label><input name="q'+str(index)+'" type="radio" required>Yes</label><label><input name="q'+str(index)+'" type="radio" required>No</label></section>'
        self.form(markup+'</div>')
        groups=inspect_screening_groups(self.page)
        self.assertEqual(len(groups),2)
        self.assertNotEqual(groups[0]['question'],groups[1]['question'])
        profile={'answers':{groups[0]['question']:'Yes',groups[1]['question']:'No'}}
        self.assertEqual(answer_verified_screening_groups(self.page,profile).choices_confirmed,2)

    def test_required_checkbox_and_other_unanswered_group_still_block_validation(self):
        self.form('<fieldset><legend>'+Q+' *</legend><label><input type="radio" name="fixture" required checked>Yes</label><label><input type="radio" name="fixture" required>No</label></fieldset><label><input type="checkbox" required>Explicit consent</label>')
        self.assertFalse(_validated_required_wizard_fields(self.page))
        self.page.locator('input[type=checkbox]').check()
        self.assertTrue(_validated_required_wizard_fields(self.page))
        self.page.locator('main').evaluate('(el)=>el.insertAdjacentHTML("beforeend",\'<input required type="radio" name="different">\')')
        self.assertFalse(_validated_required_wizard_fields(self.page))

    def test_imported_answer_reaches_review_across_all_inline_question_sections(self):
        with tempfile.TemporaryDirectory() as folder:
            private=Path(folder)/'private.json';payload=Path(folder)/'import.json'
            profile=dict(full_name='Fixture Applicant',email='fixture@example.invalid',phone='2025550123',location='Fixture City')
            private.write_text(json.dumps(profile))
            payload.write_text(json.dumps(dict(schema_version=1,answers=[dict(source='linkedin',job_id='9500000001',question=Q,answer='No')])))
            import_reviewed_answers(private,payload);profile=json.loads(private.read_text());profile['_application_job']='linkedin:9500000001'
            source=Path(folder)/'fixture_resume.pdf';source.write_bytes(b'%PDF-1.4 fixture')
            resume=import_resume(str(source),str(Path(folder)/'vault'))
            html=(ROOT/'tests/fixtures/linkedin_wizard.html').read_text()
            start=html.index(' <input id="yes"');end=html.index('</fieldset>',start)
            html=html[:start]+'<div><input id="yes" type="radio" name="relocate" required><span>Yes</span></div><div><input id="no" type="radio" name="relocate" required><span>No</span></div>'+html[end:]
            html=html.replace('Are you willing to relocate?',Q).replace('<h2>Screening questions</h2>','<section class="jobs-easy-apply-form-section"><h2>Screening questions</h2></section>')
            self.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=html))
            self.page.goto('https://www.linkedin.com/jobs/view/9500000001/?layout=inline')
            run=run_linkedin_application(self.page,profile,open_easy_apply=True,fill_application=True,advance_application=True,inspect_review=True,resume_path=str(resume),live_submission_enabled=False)
            self.assertEqual(run.flow.state,'REVIEW_INSPECTED',run.flow)
            self.assertEqual(self.page.evaluate('window.submitClicks'),0)
            evidence=dict(verification_scope='synthetic_chromium_native_radio_recovery_not_live_linkedin',raw_radio_value='on',semantic_options_verified=True,imported_answer_reached_review=True,submitted=0)
            target=ROOT/'data/native_radio_fixture_acceptance.json';target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(evidence,indent=2)+'\n')
