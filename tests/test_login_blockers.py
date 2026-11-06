import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from browser_qa import PortalQAResult, run_login_validation, classify_generic_session
from login_blockers import detect_login_blocker, google_browser_rejection, GOOGLE_BROWSER_REJECTED
from portal_session import ensure_portal_session


ERROR = "Couldn't sign you in. This browser or app may not be secure."
GOOGLE = 'https://accounts.google.com/signin/rejected?state=private-fixture-token'


class Page:
    def __init__(self, url=GOOGLE, text=ERROR, parent=None):
        self.url, self.text, self.parent = url, text, parent
        self.context = SimpleNamespace(pages=[self])
        self.goto = Mock(side_effect=AssertionError('error page must not be replaced'))

    def opener(self):
        return self.parent

    def locator(self, selector):
        return self

    def inner_text(self, **kwargs):
        return self.text


class LoginBlockerTests(unittest.TestCase):
    def test_google_rejection_is_normalized_without_echoing_oauth_url(self):
        result = classify_generic_session('indeed', GOOGLE, ERROR.replace(' ', '\n'))
        self.assertEqual(result.reason, GOOGLE_BROWSER_REJECTED)
        self.assertEqual(result.status, 'HUMAN_ACTION_REQUIRED')
        self.assertEqual(result.url, '')
        self.assertNotIn('private-fixture-token', str(result))

    def test_lookalike_and_untrusted_origins_do_not_get_google_classification(self):
        for url in ('https://accounts.google.com.evil.invalid/', 'http://accounts.google.com/',
                    'https://user@accounts.google.com/', 'https://accounts.google.com:444/',
                    'https://accounts.google.com:invalid/', 'https://www.naukri.com/login'):
            with self.subTest(url=url):
                self.assertEqual(google_browser_rejection(url, ERROR), '')

    def test_normal_google_account_chooser_is_not_a_rejection(self):
        self.assertEqual(detect_login_blocker(Page(text='Choose an account. Continue to Naukri.')), '')

    def test_related_popup_is_detected_without_reading_portal_values(self):
        main = Page('https://www.naukri.com/nlogin/login', 'portal')
        popup = Page(parent=main)
        main.context.pages.append(popup)
        self.assertEqual(detect_login_blocker(main), GOOGLE_BROWSER_REJECTED)
        main.goto.assert_not_called()

    def test_unrelated_old_google_tab_does_not_invalidate_linkedin_session(self):
        main = Page('https://www.linkedin.com/jobs/', 'Jobs My Network Messaging')
        # The same main tab may have been used for a different portal earlier.
        main.context.pages.append(Page(parent=main))
        confirmed = PortalQAResult('linkedin', 'SESSION_CONFIRMED')
        with tempfile.TemporaryDirectory() as tmp, patch('browser_qa.inspect_portal_session', return_value=confirmed), \
                patch('builtins.input', side_effect=AssertionError('confirmed session must not prompt')):
            result = run_login_validation(main, 'linkedin', str(Path(tmp) / 'status.json'), True)
        self.assertEqual(result.status, 'SESSION_CONFIRMED')

    def test_preexisting_error_stops_before_navigation_or_human_retry_prompt(self):
        page = Page()
        with tempfile.TemporaryDirectory() as tmp, patch('browser_qa.inspect_portal_session') as inspect, \
                patch('builtins.input') as prompt:
            path = Path(tmp) / 'status.json'
            result = run_login_validation(page, 'indeed', str(path), True)
            saved = json.loads(path.read_text())
        inspect.assert_not_called()
        prompt.assert_not_called()
        page.goto.assert_not_called()
        self.assertEqual(saved['indeed']['reason'], GOOGLE_BROWSER_REJECTED)
        self.assertNotIn('private-fixture-token', str(saved))
        self.assertEqual(result.status, 'HUMAN_ACTION_REQUIRED')

    def test_new_openerless_popup_is_classified_before_reloading_portal(self):
        page = Page('https://www.naukri.com/nlogin/login', 'portal')
        initial = PortalQAResult('naukri', 'LOGIN_REQUIRED')
        def human_login(_):
            page.context.pages.append(Page())
        with tempfile.TemporaryDirectory() as tmp, patch('browser_qa.inspect_portal_session', return_value=initial) as inspect, \
                patch('builtins.input', side_effect=human_login):
            result = run_login_validation(page, 'naukri', str(Path(tmp) / 'status.json'), True)
        inspect.assert_called_once()
        self.assertEqual(result.reason, GOOGLE_BROWSER_REJECTED)

    def test_same_tab_rejection_is_preserved_after_manual_login(self):
        page = Page('https://secure.indeed.com/account/login', 'portal')
        def human_login(_):
            page.url, page.text = GOOGLE, ERROR
        with tempfile.TemporaryDirectory() as tmp, patch('browser_qa.inspect_portal_session', return_value=PortalQAResult('indeed', 'LOGIN_REQUIRED')) as inspect, \
                patch('builtins.input', side_effect=human_login):
            result = run_login_validation(page, 'indeed', str(Path(tmp) / 'status.json'), True)
        inspect.assert_called_once()
        page.goto.assert_not_called()
        self.assertEqual(page.url, GOOGLE)
        self.assertEqual(result.reason, GOOGLE_BROWSER_REJECTED)

    def test_automated_session_stops_before_credentials_or_otp_lookup(self):
        page, provider = Page(), Mock()
        result = ensure_portal_session(page, 'indeed', provider)
        self.assertFalse(result.authenticated)
        self.assertEqual(result.reason, GOOGLE_BROWSER_REJECTED)
        provider.credentials.assert_not_called()
        provider.email_otp.assert_not_called()
        page.goto.assert_not_called()


if __name__ == '__main__':
    unittest.main()
