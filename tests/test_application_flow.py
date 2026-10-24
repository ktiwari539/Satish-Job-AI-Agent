import unittest
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from application_flow import run_safe_application_flow, _visible_action, _progress_scoped_next, _visible_action_texts, _click_action
from application_forms import FillPlan


class FakeAction:
    def __init__(self, text="", fail_clicks=False):
        self.clicked = False
        self.text = text
        self.fail_clicks = fail_clicks
        self.dom_clicked = False

    def count(self):
        return 1

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def click(self, timeout=0, force=False):
        if self.fail_clicks:
            raise TimeoutError("click blocked")
        self.clicked = True

    def evaluate(self, script):
        self.dom_clicked = True
        self.clicked = True

    def scroll_into_view_if_needed(self, timeout=0):
        pass

    def inner_text(self, timeout=0):
        return self.text


class EmptyAction:
    @property
    def first(self):
        return self

    def count(self):
        return 0


class Locator:
    def __init__(self, action):
        self.action = action

    @property
    def first(self):
        return self.action


class BodyLocator:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout=0):
        return self.text


class FakePage:
    url = "https://www.linkedin.com/jobs/view/1/"

    def __init__(self, mapping=None, body_text=""):
        self.mapping = mapping or {}
        self.body_text = body_text

    def locator(self, selector):
        if selector == "body":
            return BodyLocator(self.body_text)
        action = self.mapping.get(selector)
        return Locator(action) if action else EmptyAction()

    def wait_for_timeout(self, value):
        pass


class ApplicationFlowTests(unittest.TestCase):
    def test_stops_before_review(self):
        review = FakeAction()
        page = FakePage({"button:has-text('Review')": review})
        plan = FillPlan(values={"phone": "123"}, can_fill=True, reasons=("live_submission_disabled",))
        with patch("application_flow.build_page_fill_plan", return_value=plan), patch(
            "application_flow.apply_fill_plan", return_value=plan.reasons
        ):
            result = run_safe_application_flow(page, {}, advance=True)
        self.assertEqual(result.state, "REVIEW_READY")
        self.assertFalse(review.clicked)

    def test_blocks_unknown_required_fields_before_next(self):
        page = FakePage()
        plan = FillPlan(
            can_fill=True,
            unknown_required_fields=("Desired Salary",),
            reasons=("unknown_required_fields", "live_submission_disabled"),
        )
        with patch("application_flow.build_page_fill_plan", return_value=plan):
            result = run_safe_application_flow(page, {}, advance=True)
        self.assertEqual(result.state, "BLOCKED_UNKNOWN_REQUIRED_FIELDS")

    def test_review_blocks_unanswered_required_radio_without_clicking(self):
        review = FakeAction()
        page = FakePage({"button:has-text('Review')": review})
        plan = FillPlan(can_fill=True, reasons=("live_submission_disabled",))
        signals = {
            "required_radio_groups": 3, "missing_radio_groups": 1,
            "required_checkbox_groups": 0, "missing_checkbox_groups": 0,
            "unknown_required_groups": 0,
        }
        with patch("application_flow.build_page_fill_plan", return_value=plan), \
             patch("application_flow.apply_fill_plan", return_value=plan.reasons), \
             patch("application_flow._required_screening_probe",
                   return_value=signals), \
             patch("application_flow.trace_event") as trace:
            result = run_safe_application_flow(
                page, {}, advance=True, inspect_review=True,
            )
        self.assertFalse(review.clicked)
        self.assertEqual(result.state, "BLOCKED_REQUIRED_SCREENING_ANSWERS")
        self.assertIn("unanswered_required_choice_group", result.reasons)
        self.assertTrue(any(
            call.args[0] == "review_required_choice_preflight"
            for call in trace.call_args_list
        ))

    def test_unmarked_unanswered_radio_group_blocks_before_review(self):
        review = FakeAction()
        page = FakePage({"button:has-text('Review')": review})
        plan = FillPlan(can_fill=True, reasons=("live_submission_disabled",))
        signals = {
            "required_radio_groups": 0, "missing_radio_groups": 0,
            "required_checkbox_groups": 0, "missing_checkbox_groups": 0,
            "unknown_required_groups": 0,
            "visible_radio_groups": 3, "unanswered_radio_groups": 2,
        }
        with patch("application_flow.build_page_fill_plan", return_value=plan), \
             patch("application_flow.apply_fill_plan", return_value=plan.reasons), \
             patch("application_flow._required_screening_probe",
                   return_value=signals):
            result = run_safe_application_flow(
                page, {}, advance=True, inspect_review=True,
            )
        self.assertFalse(review.clicked)
        self.assertEqual(result.state, "BLOCKED_UNVERIFIED_SCREENING_CHOICES")
        self.assertIn(
            "unanswered_radio_groups_without_required_markup", result.reasons
        )

    def test_styled_hidden_radio_labels_are_included_in_browser_probe(self):
        from application_flow import _REQUIRED_SCREENING_PROBE
        self.assertIn("el.labels || []", _REQUIRED_SCREENING_PROBE)
        self.assertIn("custom_styled_radio_options", _REQUIRED_SCREENING_PROBE)
        self.assertIn("filter(activeChoice)", _REQUIRED_SCREENING_PROBE)
        self.assertNotIn("return questionText", _REQUIRED_SCREENING_PROBE)

    def test_unanswered_groups_use_distinct_radio_names_with_shared_containers(self):
        from application_flow import _REQUIRED_SCREENING_PROBE
        # Two separate employer questions can share an enclosing React form
        # component. Count each radio name independently.
        self.assertIn(
            "const key = name ? 'name:' + name : (container || radio);",
            _REQUIRED_SCREENING_PROBE,
        )
        self.assertIn("unanswered_radio_groups: unansweredRadioGroups",
                      _REQUIRED_SCREENING_PROBE)

    def test_review_validation_warning_reports_screening_counts(self):
        review = FakeAction()
        page = FakePage(
            {"button:has-text('Review')": review},
            body_text="This field is required",
        )
        plan = FillPlan(can_fill=True, reasons=("live_submission_disabled",))
        no_missing = {
            "required_radio_groups": 0, "missing_radio_groups": 0,
            "required_checkbox_groups": 0, "missing_checkbox_groups": 0,
            "unknown_required_groups": 0,
        }
        with patch("application_flow.build_page_fill_plan", return_value=plan), \
             patch("application_flow.apply_fill_plan", return_value=plan.reasons), \
             patch("application_flow._required_screening_probe",
                   side_effect=[no_missing, no_missing]), \
             patch("application_flow.trace_event") as trace:
            result = run_safe_application_flow(
                page, {}, advance=True, inspect_review=True,
            )
        self.assertTrue(review.clicked)
        self.assertEqual(result.state, "REVIEW_VALIDATION_BLOCKED")
        self.assertIn("review_validation_required_warning", result.reasons)
        self.assertTrue(any(
            call.args[0] == "review_validation_blocker_details"
            for call in trace.call_args_list
        ))

    def test_required_screening_probe_whitelists_only_structural_counts(self):
        from application_flow import _required_screening_probe
        page = FakePage()
        page.evaluate = lambda script: {
            "required_radio_groups": 2, "missing_radio_groups": 1,
            "required_checkbox_groups": 0, "missing_checkbox_groups": 0,
            "unknown_required_groups": 0,
            "resume_filename": "secret_cv.pdf",
            "answers": "private",
        }
        proof = _required_screening_probe(page)
        self.assertEqual(proof["missing_radio_groups"], 1)
        self.assertNotIn("resume_filename", proof)
        self.assertNotIn("answers", proof)

    def test_review_inspection_clicks_review_but_never_submit(self):
        review = FakeAction()
        submit = FakeAction()
        page = FakePage(
            {
                "button:has-text('Review')": review,
                "button:has-text('Submit application')": submit,
            },
            body_text="Satish Kumar Tiwari ktiwari539@gmail.com +91 8839989948",
        )
        plan = FillPlan(values={"phone": "8839989948"}, can_fill=True, reasons=("live_submission_disabled",))
        profile = {
            "full_name": "Satish Kumar Tiwari",
            "email": "ktiwari539@gmail.com",
            "phone": "8839989948",
        }
        with patch("application_flow.build_page_fill_plan", return_value=plan), patch(
            "application_flow.apply_fill_plan", return_value=plan.reasons
        ):
            result = run_safe_application_flow(
                page,
                profile,
                advance=True,
                inspect_review=True,
            )
        self.assertEqual(result.state, "REVIEW_INSPECTED")
        self.assertTrue(review.clicked)
        self.assertFalse(submit.clicked)
        self.assertEqual(result.review_mismatches, ())

    def test_live_review_with_matching_identity_becomes_submit_ready(self):
        review = FakeAction()
        submit = FakeAction()
        page = FakePage(
            {
                "button:has-text('Review')": review,
                "button:has-text('Submit application')": submit,
            },
            body_text="Satish Kumar Tiwari ktiwari539@gmail.com +91 8839989948",
        )
        plan = FillPlan(values={"phone": "8839989948"}, can_fill=True, can_submit=True)
        profile = {
            "full_name": "Satish Kumar Tiwari",
            "email": "ktiwari539@gmail.com",
            "phone": "8839989948",
            "linkedin": "https://example.invalid/profile",
        }
        with patch("application_flow.build_page_fill_plan", return_value=plan), patch(
            "application_flow.apply_fill_plan", return_value=()
        ):
            result = run_safe_application_flow(
                page,
                profile,
                advance=True,
                inspect_review=True,
                live_submission_enabled=True,
            )
        self.assertEqual(result.state, "SUBMIT_READY")
        self.assertEqual(result.review_mismatches, ())
        self.assertFalse(submit.clicked)

    def test_review_mismatch_is_reported(self):
        review = FakeAction()
        page = FakePage(
            {"button:has-text('Review')": review},
            body_text="Wrong Person other@example.com 1111111111",
        )
        plan = FillPlan(can_fill=True, reasons=("live_submission_disabled",))
        profile = {
            "full_name": "Satish Kumar Tiwari",
            "email": "ktiwari539@gmail.com",
            "phone": "8839989948",
        }
        with patch("application_flow.build_page_fill_plan", return_value=plan), patch(
            "application_flow.apply_fill_plan", return_value=plan.reasons
        ):
            result = run_safe_application_flow(
                page,
                profile,
                inspect_review=True,
            )
        self.assertEqual(result.state, "REVIEW_MISMATCH")
        self.assertIn("phone", result.review_mismatches)

    def test_aria_labeled_continue_is_supported(self):
        continue_action = FakeAction()
        page = FakePage({
            "button[aria-label*='Continue to next step']": continue_action,
        })
        plans = [
            FillPlan(values={}, can_fill=True, reasons=("live_submission_disabled",)),
            FillPlan(
                can_fill=True,
                unknown_required_fields=("Unknown question",),
                reasons=("unknown_required_fields", "live_submission_disabled"),
            ),
        ]
        with patch("application_flow.build_page_fill_plan", side_effect=plans), patch(
            "application_flow.apply_fill_plan", return_value=("live_submission_disabled",)
        ), patch(
            "application_flow._easy_apply_progress", side_effect=["1/4 pages", "2/4 pages"]
        ), patch(
            "application_flow._application_step_signature", return_value="contact"
        ), patch(
            "application_flow._blocking_confirmation_dialog", return_value=""
        ):
            result = run_safe_application_flow(page, {}, advance=True)
        self.assertTrue(continue_action.clicked)
        self.assertEqual(result.steps_completed, 1)

    def test_modal_next_is_preferred(self):
        modal_next = FakeAction()
        background_next = FakeAction()
        page = FakePage(
            {
                ".jobs-easy-apply-modal": FakeAction(),
                ".jobs-easy-apply-modal button:text-is('Next')": modal_next,
                "button:has-text('Next')": background_next,
            }
        )
        plans = [
            FillPlan(values={}, can_fill=True, reasons=("live_submission_disabled",)),
            FillPlan(
                can_fill=True,
                unknown_required_fields=("Unknown",),
                reasons=("unknown_required_fields", "live_submission_disabled"),
            ),
        ]
        with patch("application_flow.build_page_fill_plan", side_effect=plans), patch(
            "application_flow.apply_fill_plan", return_value=("live_submission_disabled",)
        ), patch(
            "application_flow._easy_apply_progress", side_effect=["1/4 pages", "2/4 pages"]
        ), patch(
            "application_flow._application_step_signature", return_value="contact"
        ), patch(
            "application_flow._blocking_confirmation_dialog", return_value=""
        ):
            result = run_safe_application_flow(page, {}, advance=True)

        self.assertTrue(modal_next.clicked)
        self.assertFalse(background_next.clicked)
        self.assertEqual(result.steps_completed, 1)

    def test_visible_actions_never_leak_resume_filenames(self):
        page = FakePage()
        page.evaluate = lambda script: [
            "Next", "Dismiss", "W private_resume_document.docx 10/18/2026",
            "Upload resume", "Candidate Email: user@example.com", "Back",
        ]
        self.assertEqual(
            _visible_action_texts(page),
            ("Next", "Dismiss", "Upload resume", "Back"),
        )

    def test_next_must_not_click_control_that_advertises_submit(self):
        class ContradictoryAction(FakeAction):
            def __init__(self):
                super().__init__(text="Next")
            def get_attribute(self, key):
                return "Submit application" if key == "aria-label" else None

        target = ContradictoryAction()
        with self.assertRaisesRegex(RuntimeError, "unsafe_next_target_advertises_submission"):
            _click_action(target, "Next")
        self.assertFalse(target.clicked)

    def test_roleless_artdeco_modal_scopes_next(self):
        inside = FakeAction(text="Next")
        behind = FakeAction(text="Next")
        page = FakePage({
            ".artdeco-modal": FakeAction(text="Apply to Example"),
            ".artdeco-modal button:text-is('Next')": inside,
            "button:text-is('Next')": behind,
        })
        found, label = _visible_action(page, ("Next",))
        self.assertIs(found, inside)
        self.assertEqual(label, "Next")
        self.assertFalse(behind.clicked)

    def test_accessible_fallback_finds_unique_enabled_next_when_modal_unrecognized(self):
        class Buttons:
            def __init__(self, controls):
                self.controls = controls

            def count(self):
                return len(self.controls)

            def nth(self, n):
                return self.controls[n]

        page = FakePage()
        enabled = FakeAction(text="Next")
        page.get_by_role = lambda role, name: Buttons([enabled])
        with patch("application_flow._easy_apply_progress", return_value="2/4 pages"):
            candidate, text = _progress_scoped_next(page)
        self.assertIs(candidate, enabled)
        self.assertEqual(text, "Next")
        self.assertFalse(enabled.clicked)

    def test_accessible_fallback_never_accepts_ambiguous_or_unsupported_context(self):
        class Buttons:
            def __init__(self, controls):
                self.controls = controls

            def count(self):
                return len(self.controls)

            def nth(self, n):
                return self.controls[n]

        first = FakeAction(text="Next")
        second = FakeAction(text="Next")
        page = FakePage()
        page.get_by_role = lambda role, name: Buttons([first, second])
        with patch("application_flow._easy_apply_progress", return_value="2/4 pages"):
            self.assertEqual(_progress_scoped_next(page), (None, ""))
        page.get_by_role = lambda role, name: Buttons([first])
        with patch("application_flow._easy_apply_progress", return_value=""):
            self.assertEqual(_progress_scoped_next(page), (None, ""))
        with patch("application_flow._easy_apply_progress", return_value="4/4 pages"):
            self.assertEqual(_progress_scoped_next(page), (None, ""))
        page.url = "https://example.com/jobs/1"
        with patch("application_flow._easy_apply_progress", return_value="2/4 pages"):
            self.assertEqual(_progress_scoped_next(page), (None, ""))
        self.assertFalse(first.clicked)
        self.assertFalse(second.clicked)

    def test_oct21_phone_contact_1_of_6_uses_unique_next_when_entry_verified(self):
        # Reproduces the user trace: a verified modal entry but no modal
        # found when seeking the visible enabled Next control.
        class Buttons:
            def __init__(self, controls):
                self.controls = controls
            def count(self):
                return len(self.controls)
            def nth(self, index):
                return self.controls[index]

        next_action = FakeAction(text="Next")
        page = FakePage(body_text="Contact info 1/6 pages Mobile phone number Next")
        original = page.locator
        page.locator = lambda selector: (
            Buttons([FakeAction(text="Dismiss"), next_action])
            if selector == 'button, [role="button"], input[type="button"], input[type="submit"]'
            else original(selector)
        )
        plans = [
            FillPlan(values={"phone": "verified"}, can_fill=True,
                     reasons=("live_submission_disabled",)),
            FillPlan(can_fill=False, unknown_required_fields=("Other question",)),
        ]
        with patch("application_flow.build_page_fill_plan", side_effect=plans), patch("application_flow.apply_fill_plan", return_value=("live_submission_disabled",)), patch("application_flow._easy_apply_progress", return_value="1/6 pages"), patch("application_flow._valid_contact_phone_step", return_value=True) as phone, patch("application_flow._wait_for_step_transition", return_value=True), patch("application_flow._blocking_confirmation_dialog", return_value=""):
            result = run_safe_application_flow(
                page, {}, advance=True, inspect_review=False,
                verified_easy_apply_modal=True,
                live_submission_enabled=False,
            )
        self.assertTrue(next_action.clicked)
        self.assertEqual(result.steps_completed, 1)
        self.assertEqual(result.state, "BLOCKED_UNKNOWN_REQUIRED_FIELDS")
        phone.assert_called()

    def test_contact_next_fallback_denied_if_entry_not_verified_or_phone_invalid(self):
        class Buttons:
            def __init__(self, controls):
                self.controls = controls
            def count(self):
                return len(self.controls)
            def nth(self, index):
                return self.controls[index]
        for verified, valid_phone in ((False, True), (True, False)):
            with self.subTest(verified=verified, valid_phone=valid_phone):
                candidate = FakeAction(text="Next")
                page = FakePage(body_text="Contact info 1/6 pages Mobile phone number Next")
                original = page.locator
                page.locator = lambda selector: (
                    Buttons([candidate])
                    if selector == 'button, [role="button"], input[type="button"], input[type="submit"]'
                    else original(selector)
                )
                with patch("application_flow._easy_apply_progress", return_value="1/6 pages"), patch("application_flow._valid_contact_phone_step", return_value=valid_phone):
                    action, label = _progress_scoped_next(
                        page, verified_contact_modal=verified
                    )
                self.assertIsNone(action)
                self.assertEqual(label, "")
                self.assertFalse(candidate.clicked)

    def test_verified_contact_with_two_next_buttons_is_still_ambiguous(self):
        class Buttons:
            def __init__(self, controls):
                self.controls = controls
            def count(self):
                return len(self.controls)
            def nth(self, index):
                return self.controls[index]
        candidates = [FakeAction(text="Next"), FakeAction(text="Next")]
        page = FakePage(body_text="Contact info 1/6 pages Mobile phone number Next")
        original = page.locator
        page.locator = lambda selector: (
            Buttons(candidates)
            if selector == 'button, [role="button"], input[type="button"], input[type="submit"]'
            else original(selector)
        )
        with patch("application_flow._easy_apply_progress", return_value="1/6 pages"), patch("application_flow._valid_contact_phone_step", return_value=True):
            button, name = _progress_scoped_next(page, verified_contact_modal=True)
        self.assertIsNone(button)
        self.assertEqual(name, "")
        self.assertFalse(any(item.clicked for item in candidates))

    def test_contact_phone_validity_probe_never_exports_or_logs_values(self):
        from application_flow import _valid_contact_phone_step
        page = FakePage()
        seen = []
        def evaluator(script):
            seen.append(script)
            return True
        page.evaluate = evaluator
        self.assertTrue(_valid_contact_phone_step(page))
        self.assertEqual(len(seen), 1)
        self.assertIn("checkValidity", seen[0])
        page.evaluate = lambda script: {"value": "SENSITIVE"}
        self.assertFalse(_valid_contact_phone_step(page))

    def test_resume_dom_next_fallback_handles_button_without_accessible_role(self):
        class NextInput(FakeAction):
            def __init__(self):
                super().__init__(text="")
            def get_attribute(self, name):
                return "Next" if name == "value" else None

        class Buttons:
            def __init__(self, controls):
                self.controls = controls
            def count(self):
                return len(self.controls)
            def nth(self, i):
                return self.controls[i]

        target = NextInput()
        page = FakePage(body_text="Apply to Example 2/4 pages Upload resume Back Next")
        original = page.locator
        def locate(selector):
            if selector == 'button, [role="button"], input[type="button"], input[type="submit"]':
                return Buttons([FakeAction(text="Back"), target])
            return original(selector)
        page.locator = locate
        with patch("application_flow._easy_apply_progress", return_value="2/4 pages"):
            found, label = _progress_scoped_next(page)
        self.assertIs(found, target)
        self.assertEqual(label, "next")
        self.assertFalse(target.clicked)

    def test_resume_dom_next_fallback_is_never_ambiguous_or_outside_resume(self):
        class Buttons:
            def __init__(self, controls):
                self.controls = controls
            def count(self):
                return len(self.controls)
            def nth(self, i):
                return self.controls[i]

        a, b = FakeAction(text="Next"), FakeAction(text="Next")
        page = FakePage(body_text="Apply to Example 2/4 pages Upload resume")
        original = page.locator
        page.locator = lambda selector: (
            Buttons([a, b]) if selector == 'button, [role="button"], input[type="button"], input[type="submit"]'
            else original(selector)
        )
        with patch("application_flow._easy_apply_progress", return_value="2/4 pages"):
            self.assertEqual(_progress_scoped_next(page), (None, ""))
        page.body_text = "Apply to Example 2/4 pages"
        with patch("application_flow._easy_apply_progress", return_value="2/4 pages"):
            self.assertEqual(_progress_scoped_next(page), (None, ""))
        page.body_text = "Apply to Example 2/4 pages Upload resume"
        with patch("application_flow._easy_apply_progress", return_value="4/4 pages"):
            self.assertEqual(_progress_scoped_next(page), (None, ""))
        self.assertFalse(a.clicked)
        self.assertFalse(b.clicked)

    def test_accessible_fallback_can_advance_realistic_resume_page(self):
        class Buttons:
            def __init__(self, controls):
                self.controls = controls

            def count(self):
                return len(self.controls)

            def nth(self, n):
                return self.controls[n]

        target = FakeAction(text="Next")
        page = FakePage(body_text="Apply to Employer 2/4 pages Upload resume Back Next")
        page.get_by_role = lambda role, name: Buttons([target])
        # A resume page can legitimately have no editable fields; Next is
        # exposed through its accessible role even if old CSS selectors fail.
        plans = [
            FillPlan(values={}, can_fill=True),
            FillPlan(unknown_required_fields=("Unknown screening answer",), can_fill=False),
        ]
        with patch("application_flow.build_page_fill_plan", side_effect=plans), \
             patch("application_flow.apply_fill_plan", return_value=()), \
             patch("application_flow._easy_apply_progress", return_value="2/4 pages"), \
             patch("application_flow._wait_for_step_transition", return_value=True), \
             patch("application_flow._blocking_confirmation_dialog", return_value=""):
            result = run_safe_application_flow(page, {}, advance=True, application_type="LINKEDIN_EASY_APPLY")
        self.assertTrue(target.clicked)
        self.assertEqual(result.steps_completed, 1)
        self.assertEqual(result.state, "BLOCKED_UNKNOWN_REQUIRED_FIELDS")

    def test_modal_next_skips_hidden_duplicate_and_finds_visible_control(self):
        class HiddenAction(FakeAction):
            def is_visible(self):
                return False

        class DuplicatedLocator:
            def __init__(self, items):
                self.items = items

            @property
            def first(self):
                return self.items[0]

            def count(self):
                return len(self.items)

            def nth(self, index):
                return self.items[index]

        stale = HiddenAction(text="Next")
        active = FakeAction(text="Next")
        base_page = FakePage({".jobs-easy-apply-modal": FakeAction()})
        original = base_page.locator

        def locate(selector):
            if selector == ".jobs-easy-apply-modal button:text-is('Next')":
                return DuplicatedLocator([stale, active])
            return original(selector)

        base_page.locator = locate
        target, action = _visible_action(base_page, ("Next",))
        self.assertIs(target, active)
        self.assertEqual(action, "Next")
        self.assertFalse(stale.clicked)

    def test_modal_next_skips_disabled_duplicate_and_finds_enabled_control(self):
        class DisabledAction(FakeAction):
            def is_enabled(self):
                return False

        class DuplicatedLocator:
            def __init__(self, items):
                self.items = items

            @property
            def first(self):
                return self.items[0]

            def count(self):
                return len(self.items)

            def nth(self, index):
                return self.items[index]

        disabled = DisabledAction(text="Next")
        enabled = FakeAction(text="Next")
        base_page = FakePage({".jobs-easy-apply-modal": FakeAction()})
        original = base_page.locator

        def locate(selector):
            if selector == ".jobs-easy-apply-modal button:text-is('Next')":
                return DuplicatedLocator([disabled, enabled])
            return original(selector)

        base_page.locator = locate
        target, action = _visible_action(base_page, ("Next",))
        self.assertIs(target, enabled)
        self.assertEqual(action, "Next")
        self.assertFalse(disabled.clicked)

    def test_disabled_next_reports_blocker_without_clicking(self):
        class DisabledAction(FakeAction):
            def is_enabled(self):
                return False

        disabled = DisabledAction(text="Next")
        page = FakePage({
            ".jobs-easy-apply-modal": FakeAction(),
            ".jobs-easy-apply-modal button:text-is('Next')": disabled,
        })
        plan = FillPlan(values={}, can_fill=True)
        diagnostic = {
            "modal_detected": True,
            "next_candidates": 1,
            "next_visible": 1,
            "next_visible_enabled": 0,
            "next_inside_modal_enabled": 0,
        }
        with patch("application_flow.build_page_fill_plan", return_value=plan), patch(
            "application_flow.apply_fill_plan", return_value=()
        ), patch(
            "application_flow._next_action_diagnostics", return_value=diagnostic
        ):
            result = run_safe_application_flow(page, {}, advance=True)
        self.assertEqual(result.state, "NO_SAFE_NEXT_ACTION")
        self.assertIn("next_control_disabled", result.reasons)
        self.assertFalse(disabled.clicked)

    def test_outside_modal_next_does_not_get_clicked_and_reports_reason(self):
        background = FakeAction(text="Next")
        page = FakePage({
            ".jobs-easy-apply-modal": FakeAction(),
            "button:text-is('Next')": background,
        })
        plan = FillPlan(values={}, can_fill=True)
        diagnostic = {
            "modal_detected": True, "next_candidates": 1,
            "next_visible": 1, "next_visible_enabled": 1,
            "next_inside_modal_enabled": 0,
        }
        with patch("application_flow.build_page_fill_plan", return_value=plan), patch(
            "application_flow.apply_fill_plan", return_value=()
        ), patch(
            "application_flow._next_action_diagnostics", return_value=diagnostic
        ):
            result = run_safe_application_flow(page, {}, advance=True)
        self.assertEqual(result.state, "NO_SAFE_NEXT_ACTION")
        self.assertIn("next_control_outside_active_modal", result.reasons)
        self.assertFalse(background.clicked)

    def test_next_click_timeout_fails_closed_without_force_or_dom_click(self):
        next_action = FakeAction(text="Next", fail_clicks=True)
        page = FakePage({
            ".jobs-easy-apply-modal": FakeAction(),
            ".jobs-easy-apply-modal button:text-is('Next')": next_action,
        })
        plan = FillPlan(values={}, can_fill=True, reasons=("live_submission_disabled",))
        with patch("application_flow.build_page_fill_plan", return_value=plan), patch(
            "application_flow.apply_fill_plan", return_value=("live_submission_disabled",)
        ), patch(
            "application_flow._easy_apply_progress", return_value="1/4 pages"
        ), patch(
            "application_flow._application_step_signature", return_value="contact"
        ), patch(
            "application_flow._blocking_confirmation_dialog", return_value=""
        ):
            result = run_safe_application_flow(page, {}, advance=True)

        self.assertFalse(next_action.dom_clicked)
        self.assertEqual(result.state, "NEXT_ACTION_FAILED")
        self.assertEqual(result.steps_completed, 0)


    def test_next_click_must_change_easy_apply_step(self):
        next_action = FakeAction()
        page = FakePage({
            ".jobs-easy-apply-modal": FakeAction(),
            ".jobs-easy-apply-modal button:text-is('Next')": next_action,
        })
        plan = FillPlan(
            values={"phone": "8839989948"},
            can_fill=True,
            reasons=("live_submission_disabled",),
        )
        with patch("application_flow.build_page_fill_plan", return_value=plan), patch(
            "application_flow.apply_fill_plan", return_value=("live_submission_disabled",)
        ), patch(
            "application_flow._easy_apply_progress", return_value="1/4 pages"
        ), patch(
            "application_flow._application_step_signature", return_value="contact-step"
        ), patch(
            "application_flow._blocking_confirmation_dialog", return_value=""
        ):
            result = run_safe_application_flow(page, {}, advance=True)

        self.assertTrue(next_action.clicked)
        self.assertEqual(result.state, "NEXT_NO_TRANSITION")
        self.assertEqual(result.steps_completed, 0)
        self.assertIn(
            "easy_apply_progress_unchanged:1/4 pages",
            result.reasons,
        )

    def test_background_next_is_not_used_when_modal_is_open(self):
        modal_root = FakeAction()
        background_next = FakeAction()
        page = FakePage({
            ".jobs-easy-apply-modal": modal_root,
            "button:text-is('Next')": background_next,
            "button:has-text('Next')": background_next,
        })
        plan = FillPlan(
            values={},
            can_fill=True,
            reasons=("live_submission_disabled",),
        )
        with patch("application_flow.build_page_fill_plan", return_value=plan), patch(
            "application_flow.apply_fill_plan", return_value=("live_submission_disabled",)
        ):
            result = run_safe_application_flow(page, {}, advance=True)

        self.assertEqual(result.state, "NO_SAFE_NEXT_ACTION")
        self.assertFalse(background_next.clicked)


    def test_generated_control_ids_do_not_count_as_step_progress(self):
        next_action = FakeAction()
        page = FakePage({
            ".jobs-easy-apply-modal": FakeAction(),
            ".jobs-easy-apply-modal button:text-is('Next')": next_action,
        })
        plan = FillPlan(
            values={"phone": "8839989948"},
            can_fill=True,
            reasons=("live_submission_disabled",),
        )
        with patch("application_flow.build_page_fill_plan", return_value=plan), patch(
            "application_flow.apply_fill_plan", return_value=("live_submission_disabled",)
        ), patch(
            "application_flow._application_step_signature",
            side_effect=["1/4 pages||Contact info|Email address*|Phone country code*|Mobile phone number*"] * 20,
        ), patch(
            "application_flow._blocking_confirmation_dialog", return_value=""
        ):
            result = run_safe_application_flow(page, {}, advance=True)

        self.assertEqual(result.state, "NEXT_NO_TRANSITION")
        self.assertEqual(result.steps_completed, 0)


    def test_visible_body_counter_prevents_unknown_progress_reason(self):
        next_action = FakeAction()
        page = FakePage(
            {
                ".jobs-easy-apply-modal": FakeAction(),
                ".jobs-easy-apply-modal button:text-is('Next')": next_action,
            },
            body_text="Apply to HG Insights Contact info 1/4 pages Email address Phone country code Mobile phone number",
        )
        plan = FillPlan(
            values={"phone": "8839989948"},
            can_fill=True,
            reasons=("live_submission_disabled",),
        )
        with patch("application_flow.build_page_fill_plan", return_value=plan), patch(
            "application_flow.apply_fill_plan", return_value=("live_submission_disabled",)
        ):
            result = run_safe_application_flow(page, {}, advance=True)

        self.assertEqual(result.state, "NEXT_NO_TRANSITION")
        self.assertEqual(result.steps_completed, 0)
        self.assertIn("easy_apply_progress_unchanged:1/4 pages", result.reasons)
        self.assertNotIn("easy_apply_progress_unchanged:unknown", result.reasons)


    def test_progress_counter_is_authoritative_over_signature_changes(self):
        next_action = FakeAction()
        page = FakePage({
            ".jobs-easy-apply-modal": FakeAction(),
            ".jobs-easy-apply-modal button:text-is('Next')": next_action,
        })
        plan = FillPlan(
            values={"phone": "8839989948"},
            can_fill=True,
            reasons=("live_submission_disabled",),
        )
        with patch("application_flow.build_page_fill_plan", return_value=plan), patch(
            "application_flow.apply_fill_plan", return_value=("live_submission_disabled",)
        ), patch(
            "application_flow._easy_apply_progress", return_value="1/4 pages"
        ), patch(
            "application_flow._application_step_signature",
            side_effect=["contact-a", "contact-b", "contact-c", "contact-d"],
        ), patch(
            "application_flow._blocking_confirmation_dialog", return_value=""
        ):
            result = run_safe_application_flow(page, {}, advance=True)

        self.assertEqual(result.state, "NEXT_NO_TRANSITION")
        self.assertEqual(result.steps_completed, 0)
        self.assertIn("easy_apply_progress_unchanged:1/4 pages", result.reasons)

    def test_save_application_dialog_blocks_flow(self):
        page = FakePage()
        with patch(
            "application_flow._blocking_confirmation_dialog",
            return_value="Save this application? Save to return to this application later.",
        ):
            result = run_safe_application_flow(page, {}, advance=True)

        self.assertEqual(result.state, "BLOCKED_CONFIRMATION_DIALOG")
        self.assertIn("unexpected_save_application_dialog", result.reasons)

    def test_clicks_next_but_never_submit(self):
        next_action = FakeAction()
        submit_action = FakeAction()
        page = FakePage(
            {
                "button:has-text('Next')": next_action,
                "button:has-text('Submit application')": submit_action,
            }
        )
        plans = [
            FillPlan(values={"phone": "123"}, can_fill=True, reasons=("live_submission_disabled",)),
            FillPlan(values={}, can_fill=True, reasons=("live_submission_disabled",)),
        ]
        with patch("application_flow.build_page_fill_plan", side_effect=plans), patch(
            "application_flow.apply_fill_plan", return_value=("live_submission_disabled",)
        ):
            result = run_safe_application_flow(page, {}, advance=True)
        self.assertEqual(result.state, "SUBMIT_READY")
        self.assertFalse(submit_action.clicked)


if __name__ == "__main__":
    unittest.main()
