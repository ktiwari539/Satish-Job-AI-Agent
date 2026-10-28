"""Real DOM simulations of extension scripts; no actual portal or Chrome API."""
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from chrome_job_import import evaluate_capture
from models import CandidateProfile

EXT = ROOT / 'browser-extension/naukri'
CAPTURE = (EXT / 'indeed_capture.js').read_text()
INSPECT = (EXT / 'application_inspection.js').read_text()
URL = 'https://in.indeed.com/viewjob?jk=0123456789abcdef'
JD = 'Customer success manager in India: onboarding stakeholder management SLA customer success. ' * 5


class ChromeExportFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.pw = sync_playwright().start(); cls.browser = cls.pw.chromium.launch(headless=True)
        except Exception:
            if os.environ.get('REQUIRE_BROWSER_FIXTURES') == '1':
                raise
            raise unittest.SkipTest('Browser fixtures unavailable')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context(); self.addCleanup(self.context.close)
        self.page = self.context.new_page()

    def route(self, url, html):
        self.context.route('**/*', lambda r: r.fulfill(status=200, content_type='text/html', body=html))
        self.page.goto(url)

    def capture_naukri(self):
        function = (EXT / 'popup.js').read_text().split('const button =')[0]
        return self.page.evaluate('() => {' + function + '\nreturn captureNaukriJobs();}')

    def test_naukri_homepage_missing_links_are_diagnostics_not_homepage_jobs(self):
        cards = ''.join('<div class="cust-job-tuple"><a class="title">Role ' + str(i) +
                        '</a><a class="comp-name">Fixture Company</a></div>' for i in range(20))
        self.route('https://www.naukri.com/mnjuser/homepage', cards)
        captured = self.capture_naukri()
        self.assertEqual(captured['jobs'], [])
        self.assertEqual(captured['diagnostics']['cards_seen'], 20)
        self.assertEqual(captured['diagnostics']['missing_posting_links'], 20)
        self.assertNotIn('/mnjuser/homepage', json.dumps(captured))

    def test_naukri_observed_posting_link_wins_over_empty_title_link(self):
        self.route('https://www.naukri.com/mnjuser/homepage', '''
          <div class="cust-job-tuple"><a class="title" href="">Customer Success Manager</a>
          <a href="/job-listings-fixture-123?tracking=PRIVATE">Job details</a><a class="comp-name">Fixture Company</a></div>
          <div class="cust-job-tuple"><a class="title" href="/mnjuser/homepage">Homepage only</a></div>''')
        captured = self.capture_naukri()
        self.assertEqual(len(captured['jobs']), 1)
        self.assertEqual(captured['jobs'][0]['url'], 'https://www.naukri.com/job-listings-fixture-123')
        self.assertEqual(captured['diagnostics']['missing_posting_links'], 1)
        self.assertNotIn('PRIVATE', json.dumps(captured))

    def test_naukri_ambiguous_or_duplicate_postings_do_not_mix_metadata(self):
        self.route('https://www.naukri.com/jobs', '''
          <div class="cust-job-tuple"><a class="title" href="/job-listings-a-123">Role A</a></div>
          <div class="cust-job-tuple"><a class="title" href="/job-listings-a-123?tracking=PRIVATE">Duplicate</a></div>
          <div class="cust-job-tuple"><a class="title" href="/job-listings-b-456">Ambiguous</a>
            <a href="/job-listings-c-789">Different job</a></div>''')
        captured = self.capture_naukri()
        self.assertEqual(len(captured['jobs']), 1)
        self.assertEqual(captured['diagnostics']['ambiguous_posting_links'], 1)
        self.assertEqual(captured['diagnostics']['duplicate_posting_links'], 1)

    def test_naukri_data_url_is_used_only_when_an_explicit_posting_url_exists(self):
        self.route('https://www.naukri.com/mnjuser/homepage', '''
          <div class="cust-job-tuple" data-url="https://www.naukri.com/job-listings-fixture-123">
            <span class="title">Customer Success Manager</span></div>
          <div class="cust-job-tuple" data-url="javascript:stealCookies()"><span class="title">Unsafe</span></div>''')
        captured = self.capture_naukri()
        self.assertEqual(len(captured['jobs']), 1)
        self.assertEqual(captured['jobs'][0]['url'], 'https://www.naukri.com/job-listings-fixture-123')

    def test_indeed_detail_to_local_review_preserves_job_id_and_no_private_values(self):
        self.route(URL + '&tracking=PRIVATE-TOKEN', '''<h1 class="jobsearch-JobInfoHeader-title">Customer Success Manager</h1>
          <div data-testid="inlineHeader-companyName">Fixture Company</div><div data-testid="inlineHeader-companyLocation">India</div>
          <div id="jobDescriptionText">''' + JD + '''</div><input type="email" required value="PRIVATE-EMAIL">
          <button onclick="window.applyClicks++">Apply now</button><script>window.applyClicks=0;
          Object.defineProperty(document.querySelector('input'),'value',{get(){throw Error('Do not read private values');}});</script>''')
        payload = self.page.evaluate(CAPTURE)
        payload['application_inspection'] = self.page.evaluate(INSPECT)
        profile = CandidateProfile.from_dict(dict(target_roles=['customer success manager'],
            skills=['customer success', 'sla', 'stakeholder management', 'onboarding'],
            skill_taxonomy=['customer success', 'sla', 'stakeholder management', 'onboarding'],
            preferred_locations=['india'], total_experience_years=8, india_authorized=True))
        private = dict(full_name='Fixture', email='fixture@example.invalid', phone='9999999999')
        store = Mock(); store.is_recent_similar_application.return_value = False
        report = evaluate_capture(payload, profile, private, SimpleNamespace(threshold=75, duplicate_cooldown_days=90), store)
        self.assertEqual(report['qualified'], 1)
        self.assertEqual(report['jobs'][0]['url'], URL)
        self.assertFalse(report['application_ready'])
        self.assertNotIn('PRIVATE-', json.dumps(payload))
        self.assertEqual(self.page.evaluate('window.applyClicks'), 0)

    def test_indeed_search_cards_keep_distinct_ids_and_never_use_selected_panel_jd(self):
        self.route('https://in.indeed.com/jobs?q=manager&vjk=fedcba9876543210', '''
          <div id="jobDescriptionText">UNRELATED selected job description</div>
          <div class="job_seen_beacon"><h2 class="jobTitle"><a href="/rc/clk?jk=0123456789abcdef&tracking=PRIVATE">Role A</a></h2></div>
          <div class="job_seen_beacon"><h2 class="jobTitle"><a href="/viewjob?jk=fedcba9876543210">Role B</a></h2></div>
          <div class="job_seen_beacon"><h2 class="jobTitle"><a href="https://evil.invalid/viewjob?jk=0123456789abcdef">Bad link</a></h2></div>''')
        report = self.page.evaluate(CAPTURE)
        self.assertEqual(len(report['jobs']), 2)
        self.assertEqual(report['page_kind'], 'search')
        self.assertNotEqual(report['jobs'][0]['url'], report['jobs'][1]['url'])
        self.assertTrue(all(not job['description'] for job in report['jobs']))
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_indeed_ambiguous_identity_and_nonjob_origins_fail_closed(self):
        html = '<h1>Customer success manager</h1><div id="jobDescriptionText">' + JD + '</div>'
        for url in (URL + '&vjk=fedcba9876543210', URL + '&jk=0123456789abcdef',
                    'https://accounts.google.com/signin', 'https://secure.indeed.com/account/login',
                    'https://indeed.com.evil.invalid/viewjob?jk=0123456789abcdef'):
            with self.subTest(url=url):
                self.context.unroute('**/*'); self.route(url, html)
                self.assertFalse(self.page.evaluate(CAPTURE)['jobs'])
                self.assertFalse(self.page.evaluate(INSPECT)['job_url'])

    def test_missing_indeed_jd_does_not_capture_body_or_profile_text(self):
        self.route(URL, '<h1>Customer success manager</h1><main>PRIVATE account/profile text</main>')
        report = self.page.evaluate(CAPTURE)
        self.assertFalse(report['jobs'])
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_existing_naukri_detail_and_inspection_still_correlate_without_apply(self):
        url = 'https://www.naukri.com/job-listings-fixture-123'
        self.route(url + '?tracking=PRIVATE', '<h1>Customer Success Manager</h1><div class="job-desc">' + JD +
                   '</div><button onclick="window.applyClicks++">Apply now</button><script>window.applyClicks=0;</script>')
        function = (EXT / 'popup.js').read_text().split('const button =')[0] + '\ncaptureNaukriJobs();'
        payload = self.page.evaluate('() => {' + function + '\nreturn captureNaukriJobs();}')
        inspection = self.page.evaluate(INSPECT)
        self.assertEqual(payload['jobs'][0]['url'], inspection['job_url'])
        self.assertEqual(inspection['portal'], 'naukri')
        self.assertEqual(self.page.evaluate('window.applyClicks'), 0)


if __name__ == '__main__':
    unittest.main()
