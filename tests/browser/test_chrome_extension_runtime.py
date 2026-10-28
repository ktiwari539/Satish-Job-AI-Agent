"""Installed Chromium extension checks; no signed-in portals or permission grant.

Unlike the Node API mocks and DOM fixtures, these load the actual manifest and
exercise native extension APIs. They do not certify a Mac permission dialog.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

EXT = Path(__file__).resolve().parents[2] / 'browser-extension/naukri'


class ChromeExtensionRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.pw = sync_playwright().start()
        except Exception:
            if os.environ.get('REQUIRE_BROWSER_FIXTURES') == '1':
                raise
            raise unittest.SkipTest('Playwright unavailable')

    @classmethod
    def tearDownClass(cls):
        cls.pw.stop()

    def installed(self, extension=EXT):
        context = self.pw.chromium.launch_persistent_context(
            '', channel='chromium', headless=True,
            ignore_default_args=['--disable-extensions'],
            args=[f'--disable-extensions-except={extension}', f'--load-extension={extension}'])
        self.addCleanup(context.close)
        worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
        return context, worker, worker.url.rsplit('/', 1)[0]

    def read_diagnostic(self, page):
        page.wait_for_function('document.getElementById("diagnostic").textContent.length > 0')
        return json.loads(page.locator('#diagnostic').inner_text())

    def test_loaded_manifest_and_native_permission_api_need_no_extra_api_permission(self):
        _, worker, _ = self.installed()
        result = worker.evaluate('''async () => ({
          manifest: chrome.runtime.getManifest(),
          api: typeof chrome.permissions.request,
          indeed: await chrome.permissions.contains({origins:['https://*.indeed.com/*']}),
          naukri: await chrome.permissions.contains({origins:['https://*.naukri.com/*']})
        })''')
        self.assertEqual(result['manifest']['version'], json.loads((EXT / 'manifest.json').read_text())['version'])
        self.assertEqual(result['api'], 'function')
        self.assertFalse(result['indeed'])
        self.assertTrue(result['naukri'])

    def test_popup_opens_stable_setup_without_requesting_permission(self):
        context, worker, origin = self.installed()
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin + '/popup.html')
        with context.expect_page() as opened:
            page.locator('#enable-indeed').click()
        setup = opened.value
        setup.wait_for_url(origin + '/indeed-access.html')
        self.assertEqual(setup.url, origin + '/indeed-access.html')
        report = self.read_diagnostic(setup)
        self.assertEqual(report['code'], 'access_not_granted')
        self.assertFalse(report['access_granted'])
        setup.locator('#check-access').click()
        self.assertFalse(worker.evaluate("() => chrome.permissions.contains({origins:['https://*.indeed.com/*']})"))
        self.assertEqual(errors, [])

    def test_loaded_old_manifest_with_new_source_has_specific_reload_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary:
            extension = Path(temporary) / 'extension'
            shutil.copytree(EXT, extension)
            manifest = json.loads((extension / 'manifest.json').read_text())
            manifest.pop('optional_host_permissions')
            manifest['version'] = '0.5.0'
            (extension / 'manifest.json').write_text(json.dumps(manifest))
            context, _, origin = self.installed(extension)
            try:
                setup = context.new_page()
                setup.goto(origin + '/indeed-access.html')
                report = self.read_diagnostic(setup)
                self.assertEqual(report['code'], 'manifest_missing_optional_host')
                self.assertEqual(report['extension_version'], '0.5.0')
                setup.locator('#request-access').click()
                self.assertEqual(self.read_diagnostic(setup)['code'], 'manifest_missing_optional_host')
            finally:
                context.close()


if __name__ == '__main__':
    unittest.main()
