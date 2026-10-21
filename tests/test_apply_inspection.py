import unittest
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from apply_inspection import (
    _candidate_application_urls,
    _inspect_external_form,
    _looks_like_application_form,
    classify_ats_provider,
    inspect_linkedin_application_entry,
    resolve_linkedin_external_url,
)
from browser_form_runtime import BrowserFieldSnapshot


class FakeButton:
    def __init__(self, text, visible=True, href=""):
        self.text = text
        self.visible = visible
        self.href = href
        self.clicked = False

    def count(self):
        return 1

    def is_visible(self):
        return self.visible

    def inner_text(self, timeout=0):
        return self.text

    def get_attribute(self, name, timeout=0):
        return self.href if name == "href" else None

    def click(self, timeout=0):
        self.clicked = True


class EmptyLocator:
    @property
    def first(self):
        return self

    def count(self):
        return 0

    def nth(self, index):
        return self

    def is_visible(self):
        return False


class ButtonLocator:
    def __init__(self, button):
        self.buttons = button if isinstance(button, (list, tuple)) else [button]

    @property
    def first(self):
        return self.buttons[0]

    def count(self):
        return len(self.buttons)

    def nth(self, index):
        return self.buttons[index]


class FakePage:
    def __init__(self, selectors):
        self.selectors = selectors
        self.url = "https://www.linkedin.com/jobs/view/123/"
        self.waited = False

    def locator(self, selector):
        button = self.selectors.get(selector)
        return ButtonLocator(button) if button else EmptyLocator()

    def wait_for_timeout(self, value):
        self.waited = True

    def wait_for_load_state(self, state, timeout=0):
        self.waited = True

    def goto(self, url, wait_until="domcontentloaded"):
        self.url = url


class ApplyInspectionTests(unittest.TestCase):
    def test_detects_easy_apply_without_clicking(self):
        button = FakeButton("Easy Apply")
        page = FakePage({"button.jobs-apply-button": button})
        result = inspect_linkedin_application_entry(page, open_easy_apply=False)
        self.assertEqual(result.application_type, "LINKEDIN_EASY_APPLY")
        self.assertEqual(result.application_state, "APPLICATION_ENTRY_FOUND")
        self.assertFalse(result.opened)
        self.assertFalse(button.clicked)

    def test_visible_entry_control_is_found_when_first_match_is_hidden(self):
        hidden = FakeButton("Start Application", visible=False)
        visible = FakeButton("Start Application", visible=True)
        page = FakePage({"a:has-text('Start Application')": [hidden, visible]})

        with patch("apply_inspection.inspect_page_fields", side_effect=((), ())):
            detected, clicked, state, reason, diagnostics = _inspect_external_form(
                page,
                "unknown",
            )

        self.assertTrue(clicked)
        self.assertTrue(visible.clicked)
        self.assertFalse(hidden.clicked)
        self.assertIn(state, {"FORM_NOT_READY", "FORM_READY"})

    def test_waits_for_client_rendered_easy_apply_button(self):
        button = FakeButton("Easy Apply")
        page = FakePage({})

        original_wait = page.wait_for_timeout
        calls = {"count": 0}

        def render_after_wait(value):
            original_wait(value)
            calls["count"] += 1
            if calls["count"] == 1:
                page.selectors["button.jobs-apply-button"] = button

        page.wait_for_timeout = render_after_wait

        result = inspect_linkedin_application_entry(page, open_easy_apply=False)

        self.assertEqual(result.application_type, "LINKEDIN_EASY_APPLY")
        self.assertEqual(result.application_state, "APPLICATION_ENTRY_FOUND")
        self.assertGreaterEqual(calls["count"], 1)
        self.assertFalse(button.clicked)

    def test_reuses_already_open_easy_apply_form(self):
        modal = FakeButton("Apply to HG Insights")
        page = FakePage({".jobs-easy-apply-modal": modal})
        fields = (
            BrowserFieldSnapshot("email", "Email address *", True),
            BrowserFieldSnapshot("phone", "Mobile phone number *", True),
        )

        with patch("apply_inspection.inspect_page_fields", return_value=fields):
            result = inspect_linkedin_application_entry(page, open_easy_apply=True)

        self.assertEqual(result.application_type, "LINKEDIN_EASY_APPLY")
        self.assertEqual(result.application_state, "FORM_READY")
        self.assertTrue(result.opened)
        self.assertFalse(result.application_entry_clicked)
        self.assertIn("reused_open_easy_apply_form", result.diagnostic_actions)

    def test_continue_button_resumes_linkedin_easy_apply(self):
        button = FakeButton("Continue")
        page = FakePage({"button:text-is('Continue')": button})
        fields = (
            BrowserFieldSnapshot("email", "Email address *", True),
            BrowserFieldSnapshot("phone", "Mobile phone number *", True),
        )
        original_click = button.click

        def opens_real_dialog(timeout=0):
            original_click(timeout=timeout)
            page.selectors[".artdeco-modal"] = FakeButton("Easy Apply dialog")

        button.click = opens_real_dialog
        with patch("apply_inspection.inspect_page_fields", return_value=fields):
            result = inspect_linkedin_application_entry(page, open_easy_apply=True)

        self.assertEqual(result.application_type, "LINKEDIN_EASY_APPLY")
        self.assertEqual(result.application_state, "FORM_READY")
        self.assertTrue(result.application_entry_clicked)
        self.assertTrue(button.clicked)

    def test_easy_apply_button_with_background_fields_but_no_modal_fails_closed(self):
        button = FakeButton("Easy Apply")
        page = FakePage({"button[aria-label*='Easy Apply']": button})
        unrelated = (
            BrowserFieldSnapshot("search", "Search jobs", False),
            BrowserFieldSnapshot("notifications", "Notifications", False, "checkbox"),
            BrowserFieldSnapshot("region", "Region", False, "select-one", ("One", "Two")),
        )
        with patch("apply_inspection.inspect_page_fields", return_value=unrelated) as inspect:
            result = inspect_linkedin_application_entry(page, open_easy_apply=True)
        self.assertTrue(button.clicked)
        self.assertEqual(result.application_state, "FORM_NOT_READY")
        self.assertEqual(result.reason, "easy_apply_modal_not_opened")
        self.assertFalse(result.opened)
        self.assertEqual(result.field_count, 0)
        inspect.assert_not_called()

    def test_roleless_artdeco_modal_is_recognized_as_real_form(self):
        button = FakeButton("Easy Apply")
        page = FakePage({"button[aria-label*='Easy Apply']": button})
        original_click = button.click

        def opens_roleless_modal(timeout=0):
            original_click(timeout=timeout)
            page.selectors[".artdeco-modal"] = FakeButton("LinkedIn modal")

        button.click = opens_roleless_modal
        fields = (BrowserFieldSnapshot("phone", "Mobile phone number *", True),)
        with patch("apply_inspection.inspect_page_fields", return_value=fields):
            result = inspect_linkedin_application_entry(page, open_easy_apply=True)
        self.assertTrue(button.clicked)
        self.assertEqual(result.application_state, "FORM_READY")
        self.assertEqual(result.field_count, 1)

    def test_similar_job_easy_apply_link_is_not_misclassified_as_external(self):
        similar_job = FakeButton(
            "Senior Manager-Customer Success Ken42 Bengaluru Easy Apply",
            href="https://www.linkedin.com/jobs/search-results/?currentJobId=4471411882",
        )
        page = FakePage({"a:has-text('Apply')": similar_job})

        result = inspect_linkedin_application_entry(page, open_easy_apply=True)

        self.assertEqual(result.application_type, "NO_APPLY_ENTRY_FOUND")
        self.assertEqual(result.application_state, "APPLICATION_ENTRY_NOT_FOUND")
        self.assertFalse(similar_job.clicked)

    def test_external_apply_is_not_opened(self):
        button = FakeButton("Apply")
        page = FakePage({"a.jobs-apply-button": button})
        result = inspect_linkedin_application_entry(page, open_easy_apply=True)
        self.assertEqual(result.application_type, "EXTERNAL_APPLY")
        self.assertFalse(result.opened)
        self.assertFalse(button.clicked)

    def test_resolves_linkedin_safety_wrapper(self):
        wrapped = (
            "https://www.linkedin.com/safety/go/?url="
            "https%3A%2F%2Fzerofox.bamboohr.com%2Fcareers%2F250"
        )
        resolved = resolve_linkedin_external_url(wrapped)
        self.assertEqual(resolved, "https://zerofox.bamboohr.com/careers/250")
        self.assertEqual(classify_ats_provider(resolved), "bamboohr")

    def test_classifies_applytojob(self):
        self.assertEqual(
            classify_ats_provider("https://hackerearth.applytojob.com/apply/abc"),
            "applytojob",
        )

    def test_bamboohr_entry_clicks_when_form_is_not_initially_visible(self):
        button = FakeButton("Apply for this job")
        page = FakePage({"a:has-text('Apply for this job')": button})
        fields = (
            (),
            (
                BrowserFieldSnapshot("firstName", "First Name *", True),
                BrowserFieldSnapshot("email", "Email", True),
            ),
        )
        with patch("apply_inspection.inspect_page_fields", side_effect=fields):
            detected, clicked, state, reason, diagnostics = _inspect_external_form(page, "bamboohr")

        self.assertTrue(clicked)
        self.assertTrue(button.clicked)
        self.assertEqual(state, "FORM_READY")
        self.assertEqual(reason, "")
        self.assertEqual(len(detected), 2)

    def test_existing_external_form_does_not_click_entry(self):
        page = FakePage({})
        fields = (
            BrowserFieldSnapshot("email", "Email Address *", True),
            BrowserFieldSnapshot("phone", "Phone *", True),
        )
        with patch("apply_inspection.inspect_page_fields", return_value=fields):
            detected, clicked, state, reason, diagnostics = _inspect_external_form(page, "applytojob")

        self.assertFalse(clicked)
        self.assertEqual(state, "FORM_READY")
        self.assertEqual(reason, "")
        self.assertEqual(len(detected), 2)

    def test_form_readiness_rejects_generic_search_controls(self):
        fields = (
            BrowserFieldSnapshot("search", "Search jobs", False),
            BrowserFieldSnapshot("location", "Location", False),
            BrowserFieldSnapshot("department", "Department", False),
        )
        self.assertFalse(_looks_like_application_form(fields))

    def test_form_readiness_accepts_candidate_identity_fields(self):
        fields = (
            BrowserFieldSnapshot("email", "Email Address", True),
            BrowserFieldSnapshot("phone", "Phone", True),
        )
        self.assertTrue(_looks_like_application_form(fields))

    def test_classifies_greythr(self):
        self.assertEqual(
            classify_ats_provider("https://company.greythr.com/hire/jobs/customer-success"),
            "greythr",
        )

    def test_bamboohr_candidate_application_routes(self):
        routes = _candidate_application_urls(
            "bamboohr",
            "https://zerofox.bamboohr.com/careers/247",
        )
        self.assertIn("https://zerofox.bamboohr.com/careers/247/application", routes)
        self.assertIn("https://zerofox.bamboohr.com/careers/247/apply", routes)

    def test_greythr_candidate_application_routes(self):
        routes = _candidate_application_urls(
            "greythr",
            "https://apport-software.greythr.com/hire/jobs/sr-customer-success-manager/",
        )
        self.assertIn(
            "https://apport-software.greythr.com/hire/jobs/sr-customer-success-manager/apply",
            routes,
        )

    def test_classifies_keka(self):
        self.assertEqual(
            classify_ats_provider("https://company.keka.com/careers/jobdetails/123"),
            "keka",
        )

    def test_custom_careers_apply_for_this_role_opens_form(self):
        button = FakeButton("Apply for this role →")
        page = FakePage({"button:has-text('Apply for this role')": button})
        fields = (
            (),
            (
                BrowserFieldSnapshot("email", "Email Address *", True),
                BrowserFieldSnapshot("phone", "Phone *", True),
            ),
        )
        with patch("apply_inspection.inspect_page_fields", side_effect=fields):
            detected, clicked, state, reason, _ = _inspect_external_form(page, "n8n_custom")
        self.assertTrue(button.clicked)
        self.assertTrue(clicked)
        self.assertEqual(state, "FORM_READY")
        self.assertEqual(reason, "")
        self.assertEqual(len(detected), 2)

    def test_classifies_n8n_custom_careers_page(self):
        self.assertEqual(
            classify_ats_provider("https://company.app.n8n.cloud/webhook/careers?id=123"),
            "n8n_custom",
        )

    def test_classifies_rippling(self):
        self.assertEqual(
            classify_ats_provider("https://ats.rippling.com/company/jobs/123/apply"),
            "rippling",
        )

    def test_missing_apply_fails_closed(self):
        page = FakePage({})
        result = inspect_linkedin_application_entry(page)
        self.assertEqual(result.application_type, "NO_APPLY_ENTRY_FOUND")
        self.assertEqual(result.application_state, "APPLICATION_ENTRY_NOT_FOUND")
        self.assertEqual(result.reason, "apply_button_not_detected_after_wait")


if __name__ == "__main__":
    unittest.main()
