"""Configured resume recovery in Chromium simulations; no live portal traffic."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from application_flow import run_safe_application_flow
from resume_evidence import inspect_resume_evidence
from resume_selection import is_resume_picker, prepare_resume_picker, resume_picker_diagnostics
from resume_store import import_resume

PROFILE = dict(full_name='Fixture Applicant', email='fixture@example.invalid', phone='2025550123')


def card(name, ident='new', selected=False, styled=False):
    style = 'style="pointer-events:none"' if styled else ''
    return (f'<div class="resume-card"><input type="radio" name="document" id="{ident}" '
            f'{"checked" if selected else ""} {style}><label for="{ident}">{name}</label></div>')


class ResumeSelectionFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.pw = sync_playwright().start()
            cls.browser = cls.pw.chromium.launch(headless=True)
            cls.verified_reviews = []
        except Exception:
            if os.environ.get('REQUIRE_BROWSER_FIXTURES') == '1':
                raise
            raise unittest.SkipTest('Chromium runtime required')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(1500)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        source = Path(folder.name) / 'configured_fixture.pdf'
        source.write_bytes(b'%PDF-1.4\n% synthetic fixture only')
        self.resume = str(import_resume(str(source), str(Path(folder.name) / 'vault')))

    def load(self, choices='', upload='', accept_upload=False, mixed=False, deferred=False, upload_delay=0):
        question = ('<fieldset><legend>Are you willing to relocate?</legend><input type="radio" '
                    'name="relocate" id="yes" required><label for="yes">Yes</label>'
                    '<input type="radio" name="relocate" id="no"><label for="no">No</label></fieldset>') if mixed else ''
        html = '''<main><section class="jobs-easy-apply-form"><p>2 / 3 pages</p><h2>Resume *</h2>
            <div id="choices">CHOICES</div>UPLOAD QUESTION<button id="review">Review</button></section></main>
            <script>window.submits=0;window.uploads=0;window.reviews=0;
            const file=document.querySelector('input[type=file]');
            if(file)file.addEventListener('change',()=>{
              window.uploads++;
              if(ACCEPT)setTimeout(()=>{const name=file.files[0].name; const box=document.createElement('div');
                box.className='resume-card'; const input=document.createElement('input');input.type='radio';
                input.name='document';input.id='accepted';const label=document.createElement('label');
                label.htmlFor='accepted';label.textContent=name;box.append(input,label);document.querySelector('#choices').append(box);},UPLOAD_DELAY);
            });
            document.querySelector('#review').onclick=()=>{
              window.reviews++; const picked=document.querySelector('input[name=document]:checked');
              const name=DEFERRED?file.files[0]?.name:(picked?.labels[0]?.textContent||document.getElementById(picked?.getAttribute('aria-labelledby'))?.textContent);
              document.querySelector('section').innerHTML='<p>3 / 3 pages</p><h2>Review your application</h2>'+
                '<p>Fixture Applicant fixture@example.invalid 2025550123</p><section class="resume-card"><h3>Resume</h3>'+
                '<a>'+name+'</a></section><button onclick="window.submits++">Submit application</button>';
            };</script>'''
        html = html.replace('UPLOAD_DELAY', str(upload_delay))
        html = html.replace('CHOICES', choices).replace('UPLOAD', upload).replace('QUESTION', question)
        html = html.replace('ACCEPT', json.dumps(accept_upload)).replace('DEFERRED', json.dumps(deferred))
        self.context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=html))
        self.page.goto('https://www.linkedin.com/jobs/view/9000000001/')

    def flow(self, profile=None):
        return run_safe_application_flow(self.page, profile or PROFILE, resume_path=self.resume,
            advance=True, inspect_review=True, verified_easy_apply_modal=True, live_submission_enabled=True)

    def assert_review(self, result, action):
        self.assertEqual(result.state, 'SUBMIT_READY', result)
        self.assertIn('resume:' + action, result.actions)
        self.assertEqual(inspect_resume_evidence(self.page, self.resume), 'matching_resume_selected')
        self.assertEqual(self.page.evaluate('window.submits'), 0)
        type(self).verified_reviews.append(dict(case=self._testMethodName,
            state=result.state, resume_action=action, identity_verified=True,
            selected_resume_verified=True, submitted=0))
        destination=ROOT/'data/resume_selection_fixture_acceptance.json'
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(json.dumps(dict(
            verification_scope='synthetic_chromium_not_live_linkedin',
            submitted=0, verified_reviews=type(self).verified_reviews),indent=2)+'\n')

    def test_saved_exact_document_replaces_wrong_selection_with_trusted_label_click(self):
        self.load(card('old_fixture.pdf', 'old', True) + card('configured_fixture.pdf', styled=True))
        self.assert_review(self.flow(), 'select_saved')
        self.assertEqual(self.page.evaluate('window.uploads'), 0)

    def test_upload_once_then_select_accepted_card_before_review(self):
        self.load(card('old_fixture.pdf', 'old', True), '<input type="file" aria-label="Resume">', accept_upload=True, upload_delay=1800)
        self.assert_review(self.flow(), 'upload_configured')
        self.assertEqual(self.page.evaluate('window.uploads'), 1)

    def test_wrapped_and_accessible_resume_titles_reach_verified_review(self):
        for heading in ('<div>Resume <small>Required</small></div>',
                        '<h5>Résumé (required)</h5>',
                        '<div role="heading" aria-label="Resume"><b>📎</b></div>'):
            with self.subTest(heading=heading):
                if self.page.url != 'about:blank':
                    self.context.unroute('**/*')
                self.load(card('old_fixture.pdf', 'old', True) + card('configured_fixture.pdf'))
                self.page.locator('h2').evaluate('(el,html)=>el.outerHTML=html', heading)
                diagnostics=resume_picker_diagnostics(self.page)
                self.assertTrue(diagnostics['heading_seen'], diagnostics)
                self.assertEqual(diagnostics['document_radio_count'], 2)
                self.assert_review(self.flow(), 'select_saved')

    def test_deep_aria_named_cards_outside_a_progress_footer_remain_in_resume_scope(self):
        self.load(card('old_fixture.pdf', 'old', True) + card('configured_fixture.pdf'))
        self.page.evaluate("""() => {
          document.querySelector('h2').outerHTML='<div>Resume <small>Required</small></div>';
          for(const input of document.querySelectorAll('input[type=radio]')){
            const box=input.parentElement, label=input.labels[0];
            const text=document.createElement('span');text.id=input.id+'-name';text.textContent=label.textContent;
            label.remove();input.setAttribute('aria-labelledby',text.id);
            let parent=box;for(let i=0;i<6;i++){const div=document.createElement('div');parent.append(div);parent=div;}
            parent.append(input);box.append(text);box.className='';
          }
          const section=document.querySelector('section');section.className='';
          const footer=document.createElement('footer');
          footer.append(document.querySelector('section>p'),document.querySelector('#choices'),document.querySelector('#review'));
          section.append(footer);
        }""")
        diagnostics=resume_picker_diagnostics(self.page)
        self.assertTrue(diagnostics['heading_seen'], diagnostics)
        self.assertEqual(diagnostics['document_radio_count'], 2)
        self.assert_review(self.flow(), 'select_saved')

    def test_document_options_under_an_employer_question_are_not_resume_choices(self):
        self.load(card('configured_fixture.pdf', selected=True))
        self.page.locator('#review').evaluate("""el=>el.insertAdjacentHTML('beforebegin',
            '<fieldset><legend>Which supporting document is required?</legend>'+
            '<label><input type="radio" name="support" required>audit_fixture.pdf</label>'+
            '<label><input type="radio" name="support">other_fixture.pdf</label></fieldset>')""")
        diagnostics=resume_picker_diagnostics(self.page)
        self.assertEqual(diagnostics['document_radio_count'], 1)
        result=self.flow()
        self.assertEqual(result.state,'BLOCKED_UNKNOWN_REQUIRED_FIELDS',result)
        self.assertIn('Which supporting document is required?',result.unknown_required_fields)
        self.assertEqual(self.page.locator('[name=support]:checked').count(),0)
        self.assertEqual(self.page.evaluate('window.reviews'),0)

    def test_two_independent_wizards_are_not_disambiguated_by_one_resume_title(self):
        self.load(card('old_fixture.pdf', 'old', True) + card('configured_fixture.pdf'))
        self.page.evaluate("""()=>{
          document.querySelector('section').className='';
          document.querySelector('main').insertAdjacentHTML('beforeend',
            '<section><p>1/3 pages</p><input name="email"><button>Next</button></section>');
        }""")
        diagnostics=resume_picker_diagnostics(self.page)
        self.assertEqual(diagnostics['status'],'no_picker',diagnostics)
        self.assertFalse(is_resume_picker(self.page))
        self.assertFalse(prepare_resume_picker(self.page,self.resume).may_advance)
        self.assertEqual(inspect_resume_evidence(self.page,self.resume),'attachment_unverified')
        self.assertTrue(self.page.locator('#old').is_checked())
        self.assertEqual(self.page.evaluate('[window.reviews,window.submits]'),[0,0])

    def test_unmapped_document_radio_is_not_reported_as_missing_applicant_fact(self):
        self.load(card('unknown_fixture.pdf', 'old', True) + card('configured_fixture.pdf'))
        self.page.locator('h2').evaluate("el=>el.remove()")
        self.page.locator('.resume-card').evaluate_all("els=>els.forEach(el=>el.className='')")
        result=self.flow()
        self.assertEqual(result.state,'BLOCKED_RESUME_UNVERIFIED',result)
        self.assertEqual(result.reasons,('resume_document_controls_unmapped',))
        self.assertEqual(result.unknown_required_fields,())
        self.assertEqual(result.resume_control_diagnostics['status'],'no_resume_heading')
        self.assertEqual(self.page.evaluate('[window.reviews,window.submits]'),[0,0])

    def test_rejected_upload_keeps_wrong_selection_and_blocks_before_review(self):
        self.load(card('old_fixture.pdf', 'old', True), '<input type="file" aria-label="Resume">')
        result = self.flow()
        self.assertEqual(result.state, 'BLOCKED_RESUME_UNVERIFIED', result)
        self.assertEqual(result.resume_evidence_state, 'different_resume_selected')
        self.assertEqual(self.page.evaluate('[window.uploads,window.reviews,window.submits]'), [1,0,0])

    def test_file_input_only_can_advance_but_requires_independent_final_review(self):
        self.load(upload='<input type="file" aria-label="Resume">', deferred=True)
        self.assert_review(self.flow(), 'upload_configured')
        self.assertEqual(self.page.evaluate('window.uploads'), 1)

    def test_ambiguous_matching_cards_are_not_chosen_arbitrarily(self):
        self.load(card('old_fixture.pdf', 'old', True) + card('configured_fixture.pdf', 'a') + card('configured_fixture.pdf', 'b'))
        result = self.flow()
        self.assertEqual(result.state, 'BLOCKED_RESUME_UNVERIFIED', result)
        self.assertTrue(self.page.locator('#old').is_checked())
        self.assertEqual(self.page.evaluate('window.reviews'), 0)

    def test_multiple_uploads_require_one_unambiguous_resume_label(self):
        for labels, expected in ((('Cover letter','Resume'), 'configured_file_pending_review'),
                                 (('Resume','Resume'), 'attachment_unverified')):
            with self.subTest(labels=labels):
                if self.page.url != 'about:blank':
                    self.context.unroute('**/*')
                self.load(upload=''.join(f'<input type="file" aria-label="{label}">' for label in labels))
                prepared = prepare_resume_picker(self.page, self.resume)
                self.assertEqual(prepared.state, expected, prepared)
                counts = self.page.locator('input[type=file]').evaluate_all('(els)=>els.map(el=>el.files.length)')
                self.assertEqual(counts, [0,1] if expected == 'configured_file_pending_review' else [0,0])

    def test_resume_choices_never_hide_an_unknown_question_on_same_step(self):
        self.load(card('configured_fixture.pdf', selected=True), mixed=True)
        result = self.flow()
        self.assertEqual(result.state, 'BLOCKED_UNKNOWN_REQUIRED_FIELDS', result)
        self.assertEqual(result.unknown_required_fields, ('Are you willing to relocate?',))
        self.assertEqual(self.page.evaluate('window.reviews'), 0)
        self.assertFalse(self.page.locator('#yes').is_checked())
        # The known answer can be verified on this mixed step without treating
        # the unselected document as an unanswered employer radio group.
        self.assert_review(self.flow({**PROFILE, 'answers': {'Are you willing to relocate?':'Yes'}}), 'already_selected')

    def test_selection_reverted_by_portal_does_not_pass_readback(self):
        self.load(card('old_fixture.pdf', 'old', True) + card('configured_fixture.pdf'))
        self.page.locator('#new').evaluate("el=>el.onchange=()=>setTimeout(()=>document.querySelector('#old').checked=true,20)")
        result = self.flow()
        self.assertEqual(result.state, 'BLOCKED_RESUME_UNVERIFIED', result)
        self.assertEqual(self.page.evaluate('window.reviews'), 0)
        self.assertTrue(self.page.locator('#old').is_checked())

    def test_independent_review_mismatch_rejects_successful_local_file_selection(self):
        self.load(upload='<input type="file" aria-label="Resume">', deferred=True)
        self.page.locator('#review').evaluate("el=>{const previous=el.onclick;el.onclick=()=>{previous();document.querySelector('.resume-card a').textContent='wrong_fixture.pdf';};}")
        result = self.flow()
        self.assertEqual(result.state, 'BLOCKED_RESUME_UNVERIFIED', result)
        self.assertEqual(inspect_resume_evidence(self.page, self.resume), 'different_resume_selected')
        self.assertEqual(self.page.evaluate('[window.uploads,window.reviews,window.submits]'), [1,1,0])

    def test_cover_letter_upload_is_never_used_for_resume(self):
        self.load(card('old_fixture.pdf', 'old', True), '<input type="file" aria-label="Cover letter">')
        result = self.flow()
        self.assertEqual(result.state, 'BLOCKED_RESUME_UNVERIFIED', result)
        self.assertEqual(self.page.evaluate('[window.uploads,window.reviews,window.submits]'), [0,0,0])

    def test_tampered_vault_cannot_upload_or_change_selection(self):
        self.load(card('old_fixture.pdf', 'old', True), '<input type="file" aria-label="Resume">')
        Path(self.resume).write_bytes(b'%PDF-1.4\n% changed bytes')
        prepared = prepare_resume_picker(self.page, self.resume)
        self.assertEqual(prepared.state, 'resume_provenance_invalid')
        self.assertEqual(self.page.evaluate('window.uploads'), 0)
        self.assertTrue(self.page.locator('#old').is_checked())

    def test_final_review_is_read_only_even_with_resume_controls(self):
        self.load(card('old_fixture.pdf', 'old', True), '<input type="file" aria-label="Resume">')
        self.page.locator('#review').evaluate("el=>el.textContent='Submit application'")
        self.assertFalse(is_resume_picker(self.page))
        prepared = prepare_resume_picker(self.page, self.resume)
        self.assertFalse(prepared.may_advance)
        self.assertEqual(self.page.evaluate('window.uploads'), 0)
        self.assertTrue(self.page.locator('#old').is_checked())


if __name__ == '__main__':
    unittest.main()
