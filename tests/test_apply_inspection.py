import unittest
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from apply_inspection import (
    _candidate_application_urls,
    _inspect_external_form,
    _looks_like_application_form,
    classify_ats_provider,
    inspect_linkedin_application_entry,
    _post_click_easy_apply_probe,
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
        self.assertGreaterEqual(inspect.call_count, 1)

    def test_easy_apply_recovers_after_one_verified_no_change_click(self):
        from apply_inspection import _post_click_easy_apply_probe
        button = FakeButton("Easy Apply")
        page = FakePage({"button[aria-label*='Easy Apply']": button})
        page.url = "https://www.linkedin.com/jobs/view/4480053196/"
        clicks = {"n": 0}

        def delayed_second_click(timeout=0):
            clicks["n"] += 1
            if clicks["n"] == 2:
                page.selectors[".artdeco-modal"] = FakeButton("LinkedIn form")

        button.click = delayed_second_click
        # The main page had a pre-existing unrelated Submit. The application
        # UI and field count are unchanged after the first click.
        page.evaluate = lambda script: {
            "candidate_modal_count": 0, "main_document_input_count": 18,
            "visible_submit_count": 1, "enabled_next_count": 0,
            "visible_easy_apply_cta_count": 1, "visible_form_count": 0,
            "submit_in_application_container_count": 0,
        }
        field = BrowserFieldSnapshot("phone", "Mobile phone *", True, "tel")
        def field_reader(_page):
            return (field,) if clicks["n"] == 2 else ()

        with patch("apply_inspection.inspect_page_fields", side_effect=field_reader):
            outcome = inspect_linkedin_application_entry(page, open_easy_apply=True)
        self.assertEqual(clicks["n"], 2)
        self.assertEqual(outcome.application_state, "FORM_READY")
        self.assertEqual(outcome.field_count, 1)

    def test_easy_apply_never_retries_with_new_submit_or_changed_structure(self):
        from apply_inspection import _retry_safe_easy_apply_cta
        button = FakeButton("Easy Apply")
        page = FakePage({})
        baseline = {
            "route_state": "same_exact_job",
            "observable_form_structure_changed": False,
            "wizard_progress_present": False,
            "candidate_modal_count": 0,
            "visible_easy_apply_cta_count": 1,
            "preclick_visible_easy_apply_cta_count": 1,
            "visible_submit_count": 1,
            "preclick_visible_submit_count": 1,
        }
        for override in (
            {"route_state": "different_linkedin_job"},
            {"observable_form_structure_changed": True},
            {"wizard_progress_present": True},
            {"candidate_modal_count": 1},
            {"visible_easy_apply_cta_count": 0},
            {"visible_submit_count": 2},
        ):
            with self.subTest(override=override):
                self.assertFalse(
                    _retry_safe_easy_apply_cta(page, button, {**baseline, **override})
                )
        self.assertFalse(button.clicked)

    def test_async_modal_render_is_detected_without_second_click(self):
        button = FakeButton("Easy Apply")
        page = FakePage({"button[aria-label*='Easy Apply']": button})
        page.url = "https://www.linkedin.com/jobs/view/4480053196/"
        click_count = {"n": 0}
        render = {"ready": False, "waits": 0}
        original_wait = page.wait_for_timeout

        def click(timeout=0):
            click_count["n"] += 1

        def wait(ms):
            original_wait(ms)
            render["waits"] += 1
            if render["waits"] >= 3:
                render["ready"] = True
                page.selectors[".artdeco-modal"] = FakeButton("Application")

        button.click = click
        page.wait_for_timeout = wait
        field = BrowserFieldSnapshot("phone", "Mobile phone *", True, "tel")
        with patch("apply_inspection.inspect_page_fields",
                   side_effect=lambda _: (field,) if render["ready"] else ()):
            result = inspect_linkedin_application_entry(
                page, open_easy_apply=True
            )
        self.assertEqual(result.application_state, "FORM_READY")
        self.assertEqual(click_count["n"], 1)
        self.assertTrue(render["ready"])

    def test_easy_apply_recovers_no_more_than_once(self):
        button = FakeButton("Easy Apply")
        page = FakePage({"button[aria-label*='Easy Apply']": button})
        page.url = "https://www.linkedin.com/jobs/view/4480053196/"
        clicks = {"count": 0}

        def no_effect(timeout=0):
            clicks["count"] += 1

        button.click = no_effect
        page.evaluate = lambda _script: {
            "candidate_modal_count": 0, "main_document_input_count": 18,
            "visible_submit_count": 1, "enabled_next_count": 0,
            "visible_easy_apply_cta_count": 1, "visible_form_count": 0,
            "submit_in_application_container_count": 0,
        }
        with patch("apply_inspection.inspect_page_fields", return_value=()):
            outcome = inspect_linkedin_application_entry(
                page, open_easy_apply=True
            )
        self.assertEqual(clicks["count"], 2)
        self.assertEqual(outcome.application_state, "FORM_NOT_READY")
        self.assertFalse(outcome.opened)

    def test_oct22_real_inline_contact_wizard_without_modal_is_form_ready(self):
        """Replay the actual log: 1/6 page, eight fields, five required,
        no dialog node; exact job path remains but tracking query changes.
        """
        button = FakeButton("Easy Apply")
        page = FakePage({"button[aria-label*='Easy Apply']": button})
        page.url = "https://www.linkedin.com/jobs/view/4461542106/"
        before = button.click
        def open_inline_wizard(timeout=0):
            before(timeout=timeout)
            page.url += "?companyName=Firework&trackingId=redacted"
        button.click = open_inline_wizard
        page.evaluate = lambda script: True
        fields = (
            BrowserFieldSnapshot("firstName", "First name *", True),
            BrowserFieldSnapshot("lastName", "Last name *", True),
            BrowserFieldSnapshot("country", "Country *", True, "select-one"),
            BrowserFieldSnapshot("phone", "Mobile phone *", True, "tel"),
            BrowserFieldSnapshot("phoneType", "Phone type *", True, "select-one"),
            BrowserFieldSnapshot("address", "Address", False),
            BrowserFieldSnapshot("consent", "Consent", False, "checkbox"),
            BrowserFieldSnapshot("extra", "Additional", False, "select-one"),
        )
        with patch("apply_inspection.inspect_page_fields", return_value=fields), \
             patch("apply_inspection.trace_event") as trace:
            result = inspect_linkedin_application_entry(page, open_easy_apply=True)
        self.assertTrue(button.clicked)
        self.assertEqual(result.application_type, "LINKEDIN_EASY_APPLY")
        self.assertEqual(result.application_state, "FORM_READY")
        self.assertTrue(result.opened)
        self.assertEqual(result.required_field_count, 5)
        self.assertEqual(result.field_count, 8)
        self.assertTrue(any(
            call.args[0] == "easy_apply_inline_wizard_verified"
            for call in trace.call_args_list
        ))

    def test_inline_wizard_requires_exact_job_url_and_fields(self):
        from apply_inspection import _verified_inline_easy_apply_wizard
        page = FakePage({})
        page.url = "https://www.linkedin.com/jobs/view/4461542106/?trackingId=redacted"
        page.evaluate = lambda script: True
        fields = (
            BrowserFieldSnapshot("firstName", "First name *", True),
            BrowserFieldSnapshot("lastName", "Last name *", True),
            BrowserFieldSnapshot("country", "Country *", True, "select-one"),
            BrowserFieldSnapshot("phone", "Mobile phone *", True, "tel"),
        )
        yes = "https://www.linkedin.com/jobs/view/4461542106/"
        self.assertTrue(_verified_inline_easy_apply_wizard(
            page, job_url_before=yes, fields=fields
        ))
        for wrong in (
            "https://www.linkedin.com/jobs/view/4476701830/",
            "https://other.example/jobs/view/4461542106/",
            "https://www.linkedin.com/jobs/search/",
        ):
            with self.subTest(wrong=wrong):
                self.assertFalse(_verified_inline_easy_apply_wizard(
                    page, job_url_before=wrong, fields=fields
                ))
        self.assertFalse(_verified_inline_easy_apply_wizard(
            page, job_url_before=yes, fields=fields[:2]
        ))
        no_phone = fields[:3] + (
            BrowserFieldSnapshot("extra", "Other", False),
        )
        self.assertFalse(_verified_inline_easy_apply_wizard(
            page, job_url_before=yes, fields=no_phone
        ))
        page.evaluate = lambda script: False
        self.assertFalse(_verified_inline_easy_apply_wizard(
            page, job_url_before=yes, fields=fields
        ))

    def test_no_modal_and_no_verified_wizard_does_not_start_form_navigation(self):
        button = FakeButton("Easy Apply")
        page = FakePage({"button[aria-label*='Easy Apply']": button})
        page.url = "https://www.linkedin.com/jobs/view/4461542106/"
        page.evaluate = lambda script: False
        fields = (
            BrowserFieldSnapshot("name", "Name *", True),
            BrowserFieldSnapshot("lastName", "Last Name *", True),
            BrowserFieldSnapshot("email", "Email *", True),
            BrowserFieldSnapshot("phone", "Phone *", True, "tel"),
        )
        with patch("apply_inspection.inspect_page_fields", return_value=fields):
            result = inspect_linkedin_application_entry(page, open_easy_apply=True)
        self.assertEqual(result.application_state, "FORM_NOT_READY")
        self.assertFalse(result.opened)
        self.assertEqual(result.reason, "easy_apply_modal_not_opened")

    def test_post_click_probe_reports_new_tab_and_iframe_without_sensitive_data(self):
        page = FakePage({})
        page.context = SimpleNamespace(pages=[object(), object()])
        page.url = "https://www.linkedin.com/jobs/view/4409454707/?trackingId=PRIVATE"
        page.evaluate = lambda code: {
            "iframe_count": 1,
            "candidate_modal_count": 0,
            "main_document_input_count": 3,
            "page_hidden": False,
            "private_email": "private@example.invalid",
            "input_values": ["1234567890"],
        }
        with patch("apply_inspection.trace_event") as trace:
            signals = _post_click_easy_apply_probe(
                page,
                url_before="https://www.linkedin.com/jobs/view/4409454707/",
                pages_before=1,
            )
        self.assertTrue(signals["url_changed"])
        self.assertEqual(signals["new_browser_pages"], 1)
        self.assertEqual(signals["iframe_count"], 1)
        self.assertEqual(signals["main_document_input_count"], 3)
        self.assertNotIn("private_email", signals)
        self.assertNotIn("input_values", signals)
        self.assertEqual(trace.call_args.args[0], "easy_apply_post_click_probe")

    def test_probe_comparison_identifies_preexisting_submit_without_values(self):
        page = FakePage({})
        page.url = "https://www.linkedin.com/jobs/view/4480053196/?trackingId=PRIVATE"
        page.evaluate = lambda _script: {
            "iframe_count": 5, "candidate_modal_count": 0,
            "main_document_input_count": 18, "visible_form_count": 0,
            "visible_easy_apply_cta_count": 1,
            "visible_submit_count": 1, "enabled_next_count": 0,
            "submit_in_application_container_count": 0,
            "submit_in_job_alert_count": 1,
            "private_email": "private@example.invalid",
        }
        with patch("apply_inspection.trace_event") as trace:
            baseline = _post_click_easy_apply_probe(
                page, url_before="https://www.linkedin.com/jobs/view/4480053196/",
                pages_before=0, emit_trace=False,
            )
            self.assertEqual(trace.call_count, 0)
            after = _post_click_easy_apply_probe(
                page, url_before="https://www.linkedin.com/jobs/view/4480053196/",
                pages_before=0, baseline=baseline,
            )
        self.assertEqual(trace.call_count, 1)
        self.assertTrue(after["visible_submit_preexisting"])
        self.assertEqual(after["preclick_visible_submit_count"], 1)
        self.assertFalse(after["observable_form_structure_changed"])
        self.assertEqual(after["observed_input_count_delta"], 0)
        self.assertEqual(after["submit_in_job_alert_count"], 1)
        self.assertNotIn("PRIVATE", str(after))
        self.assertNotIn("private@example.invalid", str(after))

    def test_probe_comparison_detects_new_application_structure_but_never_approves(self):
        page = FakePage({})
        page.url = "https://www.linkedin.com/jobs/view/4480053196/"
        page.evaluate = lambda _script: {
            "candidate_modal_count": 1, "main_document_input_count": 24,
            "visible_submit_count": 0, "enabled_next_count": 1,
            "visible_easy_apply_cta_count": 1, "visible_form_count": 1,
            "submit_in_application_container_count": 0,
        }
        baseline = {
            "candidate_modal_count": 0, "main_document_input_count": 18,
            "visible_submit_count": 1, "enabled_next_count": 0,
            "visible_easy_apply_cta_count": 1, "visible_form_count": 0,
            "submit_in_application_container_count": 0,
        }
        with patch("apply_inspection.trace_event"):
            after = _post_click_easy_apply_probe(
                page, url_before=page.url,
                pages_before=0, baseline=baseline,
            )
        self.assertTrue(after["observable_form_structure_changed"])
        self.assertFalse(after["visible_submit_preexisting"] is False)
        self.assertEqual(after["observed_input_count_delta"], 6)

    def test_oct23_submit_control_after_click_is_diagnosed_without_form_access(self):
        """Crewlia trace: zero modal/Next, visible Submit, no verified first page."""
        button = FakeButton("Easy Apply")
        page = FakePage({"button[aria-label*='Easy Apply']": button})
        page.url = "https://www.linkedin.com/jobs/view/4480053196/"
        old_click = button.click

        def change_tracking_query(timeout=0):
            old_click(timeout=timeout)
            page.url += "?trackingId=PRIVATE_VALUE"

        button.click = change_tracking_query
        page.evaluate = lambda source: {
            "iframe_count": 5, "candidate_modal_count": 0,
            "main_document_input_count": 18,
            "visible_submit_count": 1, "enabled_next_count": 0,
            "wizard_progress_present": False,
            "wizard_final_page": False,
            "page_hidden": False, "secret": "private@example.com",
        }
        fields = (
            BrowserFieldSnapshot("email", "Email *", True),
            BrowserFieldSnapshot("country", "Country *", True),
            BrowserFieldSnapshot("phone", "Phone *", True, "tel"),
            BrowserFieldSnapshot("firstName", "First name *", True),
        )
        with patch("apply_inspection.inspect_page_fields", return_value=fields), \
             patch("apply_inspection.trace_event") as trace:
            result = inspect_linkedin_application_entry(page, open_easy_apply=True)
        self.assertTrue(button.clicked)
        self.assertEqual(result.application_state, "FORM_NOT_READY")
        self.assertFalse(result.opened)
        self.assertEqual(
            result.reason, "easy_apply_unscoped_submit_control"
        )
        observations = [
            call.kwargs for call in trace.call_args_list
            if call.args[0] == "easy_apply_post_click_probe"
        ]
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["route_state"], "same_exact_job")
        self.assertEqual(observations[0]["visible_submit_count"], 1)
        self.assertEqual(observations[0]["enabled_next_count"], 0)
        self.assertNotIn("PRIVATE_VALUE", str(observations))
        self.assertNotIn("private@example.com", str(observations))

    def test_one_step_application_signal_requires_form_scope_and_never_approves(self):
        from apply_inspection import _post_click_unverified_reason
        base = {
            "route_state": "same_exact_job",
            "visible_submit_count": 1,
            "submit_in_application_container_count": 1,
            "submit_container_has_contact_fields": True,
        }
        self.assertEqual(
            _post_click_unverified_reason(base),
            "easy_apply_possible_single_step_form_unverified",
        )
        self.assertEqual(
            _post_click_unverified_reason({
                **base, "submit_container_has_contact_fields": False
            }),
            "easy_apply_submit_visible_without_verified_wizard",
        )
        self.assertEqual(
            _post_click_unverified_reason({
                **base, "submit_in_application_container_count": 0
            }),
            "easy_apply_unscoped_submit_control",
        )

    def test_post_click_different_job_or_route_never_approves_form(self):
        for destination in (
            "https://www.linkedin.com/jobs/view/4485555555/",
            "https://www.linkedin.com/jobs/search/?currentJobId=4480053196",
            "https://external.example/apply",
        ):
            with self.subTest(destination=destination):
                button = FakeButton("Easy Apply")
                page = FakePage({"button[aria-label*='Easy Apply']": button})
                page.url = "https://www.linkedin.com/jobs/view/4480053196/"
                original = button.click

                def redirected(timeout=0):
                    original(timeout=timeout)
                    page.url = destination

                button.click = redirected
                page.evaluate = lambda source: False
                with patch("apply_inspection.inspect_page_fields", return_value=()):
                    result = inspect_linkedin_application_entry(
                        page, open_easy_apply=True
                    )
                self.assertEqual(result.application_state, "FORM_NOT_READY")
                self.assertFalse(result.opened)
                self.assertEqual(result.reason, "easy_apply_unverified_navigation")

    def test_post_click_route_summary_drops_tracking_parameters(self):
        from apply_inspection import _post_click_route_state
        before = "https://www.linkedin.com/jobs/view/4480053196/"
        self.assertEqual(
            _post_click_route_state(before, before + "?trackingId=PRIVATE_VALUE"),
            "same_exact_job",
        )
        self.assertEqual(
            _post_click_route_state(before,
                                    "https://www.linkedin.com/jobs/view/4485555555/"),
            "different_linkedin_job",
        )
        self.assertEqual(
            _post_click_route_state(before, "https://example.net/apply"),
            "left_linkedin",
        )

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
