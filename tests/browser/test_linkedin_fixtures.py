"""Real Chromium, synthetic routes/people only. This is NOT live LinkedIn QA."""
import json
import io
from contextlib import redirect_stdout
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from apply_inspection import inspect_linkedin_application_entry, _inspect_external_form
from application_flow import run_safe_application_flow
from linkedin_entry_diagnostics import classify_linkedin_entry
from resume_evidence import inspect_resume_evidence
from resume_store import import_resume
from release_acceptance import review_identity_verified
from easy_apply_debug import debug_easy_apply
from store import JobStore
from smart_debug_queue import debug_easy_apply_queue
from certify_linkedin import summarize

PROFILE = dict(full_name='Fixture Applicant', email='fixture@example.invalid',
               phone='2025550123', location='Fixture City', relocation='Yes',
               answers={'Are you willing to relocate?': 'Yes'})


class BrowserFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.pw = sync_playwright().start()
            cls.browser = cls.pw.chromium.launch(headless=True)
        except Exception:
            if os.environ.get('REQUIRE_BROWSER_FIXTURES') == '1':
                raise
            raise unittest.SkipTest('Install tests/browser/requirements.txt and Chromium')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(1500)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        source = Path(self.folder.name) / 'fixture_resume.pdf'
        source.write_bytes(b'%PDF-1.4\n% synthetic fixture only')
        self.resume = str(import_resume(str(source), str(Path(self.folder.name) / 'vault')))

    def load(self, html=None, query='', jid='9000000001'):
        document = html if html is not None else (ROOT / 'tests/fixtures/linkedin_wizard.html').read_text()
        self.context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=document))
        self.page.goto('https://www.linkedin.com/jobs/view/' + jid + '/' + query)
        return self.page

    def flow(self, **options):
        return run_safe_application_flow(self.page, PROFILE, resume_path=self.resume,
            advance=True, inspect_review=True, verified_easy_apply_modal=True, **options)

    def test_modal_and_inline_reach_review_with_selected_resume_and_zero_submits(self):
        for layout in ('modal', 'inline'):
            with self.subTest(layout=layout):
                self.load(query='?layout='+layout)
                entry = inspect_linkedin_application_entry(self.page, open_easy_apply=True)
                self.assertEqual(entry.application_state, 'FORM_READY')
                result = self.flow()
                self.assertEqual(result.state, 'REVIEW_INSPECTED', result)
                self.assertTrue(review_identity_verified(PROFILE, result.review_checks))
                self.assertEqual(inspect_resume_evidence(self.page, self.resume), 'matching_resume_selected')
                self.assertEqual(self.page.evaluate('window.submitClicks'), 0)
                self.context.unroute('**/*')

    def test_unknown_screening_answer_blocks_then_next_distinct_job_can_run(self):
        self.load(query='?unknown=1')
        inspect_linkedin_application_entry(self.page, open_easy_apply=True)
        result = self.flow()
        self.assertTrue(result.state.startswith('BLOCKED_'), result)
        self.assertEqual(self.page.evaluate('window.step'), 3)
        self.assertFalse(self.page.locator('#yes').is_checked())
        self.assertFalse(self.page.locator('#no').is_checked())
        self.assertEqual(self.page.evaluate('window.submitClicks'), 0)
        self.context.unroute('**/*')
        self.load(jid='9000000002')
        inspect_linkedin_application_entry(self.page, open_easy_apply=True)
        self.assertEqual(self.flow().state, 'REVIEW_INSPECTED')

    def test_wrong_resume_fails_live_readiness_without_submitting(self):
        self.load(query='?wrong=1')
        inspect_linkedin_application_entry(self.page, open_easy_apply=True)
        self.assertEqual(self.flow(live_submission_enabled=True).state, 'BLOCKED_RESUME_UNVERIFIED')
        self.assertEqual(self.page.evaluate('window.submitClicks'), 0)

    def test_stalled_next_is_bounded(self):
        self.load(query='?stalled=1')
        inspect_linkedin_application_entry(self.page, open_easy_apply=True)
        result = self.flow(max_steps=3)
        self.assertEqual(result.state, 'NEXT_NO_TRANSITION', result)
        self.assertEqual(self.page.evaluate('window.submitClicks'), 0)

    def test_entry_classes_and_aria_cta(self):
        cases = [
            ('<button class="jobs-apply-button">Apply</button>', 'EXTERNAL_APPLY'),
            ('<a class="jobs-apply-button" href="https://jobs.lever.co/example/fixture">Apply</a>', 'EXTERNAL_APPLY'),
            ('<button>Applied</button>', 'ALREADY_APPLIED'),
            ('<p>No longer accepting applications</p>', 'UNAVAILABLE'),
            ('<p>Unrecognized controls</p>', 'SELECTOR_LAYOUT_FAILURE'),
            ('<div role="button" aria-label="Easy Apply">Easy Apply</div>', 'EASY_APPLY'),
        ]
        for body, expected in cases:
            with self.subTest(expected=expected):
                self.load('<main><h1>Fixture job</h1>'+body+'</main>')
                entry = inspect_linkedin_application_entry(self.page)
                actual = classify_linkedin_entry(self.page, self.page.url, entry=entry)
                self.assertEqual(actual['entry_classification'], expected)
                self.context.unroute('**/*')

    def test_resume_exact_match_scope_and_native_hidden_radio(self):
        for name, expected in [('evilfixture_resume.pdf', 'different_resume_selected'),
                               ('fixture_resume.pdf.bak', 'attachment_unverified'),
                               ('fixture_resume.pdf', 'matching_resume_selected')]:
            with self.subTest(name=name):
                self.load('<aside>fixture_resume.pdf</aside><div role="dialog">'
                    '<label><input type="radio" checked style="display:none">'+name+'</label></div>')
                self.assertEqual(inspect_resume_evidence(self.page, self.resume), expected)
                self.context.unroute('**/*')

    def test_file_input_and_background_filename_never_prove_attachment(self):
        self.load('<aside>fixture_resume.pdf</aside><div role="dialog"><input type="file"></div>')
        self.page.locator('input').set_input_files(self.resume)
        self.assertEqual(inspect_resume_evidence(self.page, self.resume), 'file_input_selected_unconfirmed')

    def test_ten_distinct_synthetic_jobs_through_real_queue_and_persistent_skips(self):
        """Only browser creation/route responses are injected; application code is real."""
        owner = self
        job_ids = [str(9100000000+i) for i in range(10)]
        profile = Path(self.folder.name) / 'profile.json'
        profile.write_text(json.dumps(PROFILE))
        db = str(Path(self.folder.name) / 'jobs.db')
        JobStore(db)
        html = (ROOT / 'tests/fixtures/linkedin_wizard.html').read_text()
        submissions = []
        class FixtureRuntime:
            def __init__(self, config):
                self.context = owner.browser.new_context()
                def respond(route):
                    url = route.request.url
                    if '/jobs/search/' in url:
                        body = '<main>' + ''.join(
                            '<li class="scaffold-layout__list-item"><a class="job-card-list__title--link" href="https://www.linkedin.com/jobs/view/'+jid+'/">Customer Success Manager</a></li>'
                            for jid in job_ids) + '</main>'
                    elif '/feed/' in url:
                        body = '<main>Jobs Messaging Notifications</main>'
                    else:
                        body = html
                        if job_ids[0] in url:  # Unknown truth blocks; queue must advance.
                            body = body.replace("const unknown = new URLSearchParams(location.search).has('unknown');", 'const unknown = true;')
                    route.fulfill(status=200, content_type='text/html', body=body)
                self.context.route('**/*', respond)
                self.page = self.context.new_page()
                self.page.set_default_timeout(1500)
            def __enter__(self):
                return self
            def __exit__(self, *_):
                submissions.append(self.page.evaluate('window.submitClicks || 0'))
                self.context.close()
        args = SimpleNamespace(portal='linkedin', query='Customer Success Manager', location='India',
            max_jobs=20, smart_max_forms=5, job_url='', debug_easy_apply_only=True, smart_debug=True,
            smart_debug_queue=True, debug_interactive=False, debug_hold_seconds=0, profile_dir='unused-fixture',
            headless=True, approve_one_live_application=False, allow_outside_window=False,
            private_profile=str(profile), resume_path=self.resume, db=db)
        results=[]
        with patch('smart_debug_queue.PlaywrightSession', FixtureRuntime), \
             patch('easy_apply_debug.PlaywrightSession', FixtureRuntime):
            for _ in range(2):
                with redirect_stdout(io.StringIO()) as output:
                    debug_easy_apply_queue(args)
                report = json.loads(output.getvalue().splitlines()[-1])
                self.assertEqual(report['forms_checked'], 5, report)
                results.extend(report['results'])
            # Repeated discovery must not reopen these same jobs.
            with redirect_stdout(io.StringIO()) as output:
                debug_easy_apply_queue(args)
            self.assertEqual(json.loads(output.getvalue().splitlines()[-1])['checked'], 0)
        self.assertEqual(sum(submissions), 0)
        report = summarize(results)
        self.assertEqual(report['distinct_application_forms_exercised'], 10)
        self.assertEqual(report['release_ready_jobs'], 9, results)
        self.assertTrue(report['acceptance_passed'])
        report['verification_scope'] = 'synthetic_Chromium_fixtures_only_NOT_live_LinkedIn'
        report['submit_clicks_observed'] = sum(submissions)
        report['unknown_screening_jobs_blocked'] = 1
        artifact = ROOT / 'data/fixture_acceptance.json'
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(report, indent=2, sort_keys=True))

    def test_external_lever_and_greenhouse_fill_only(self):
        for provider in ('lever', 'greenhouse'):
            with self.subTest(provider=provider):
                self.load('<main><form><label for="full_name">Full name *</label><input id="full_name" required>'
                    '<label for="email">Email address *</label><input type="email" id="email" required>'
                    '<label for="phone">Phone *</label><input id="phone" required>'
                    '<label for="resume">Resume</label><input type="file" id="resume">'
                    '<button type="button" onclick="window.submitClicks++">Submit application</button>'
                    '</form></main><script>window.submitClicks=0</script>')
                fields, _, state, _, _ = _inspect_external_form(self.page, provider)
                self.assertEqual(state, 'FORM_READY')
                result = run_safe_application_flow(self.page, PROFILE, resume_path=self.resume,
                    advance=True, inspect_review=True, application_type='EXTERNAL_APPLY')
                self.assertNotEqual(result.state, 'SUBMIT_READY')
                self.assertEqual(self.page.locator('#email').input_value(), PROFILE['email'])
                self.assertEqual(self.page.evaluate('window.submitClicks'), 0)
                self.context.unroute('**/*')


if __name__ == '__main__':
    unittest.main()
