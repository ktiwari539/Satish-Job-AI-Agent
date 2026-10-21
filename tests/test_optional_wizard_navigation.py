"""Real-log regression: optional-only 4/6 can safely reach a review gate."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from application_flow import (
    _progress_scoped_next, _validated_required_wizard_fields,
    run_safe_application_flow,
)
from application_forms import FillPlan


class Button:
    def __init__(self, name, page=None):
        self.name = name
        self.page = page
        self.clicked = 0

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def inner_text(self, timeout=0):
        return self.name

    def get_attribute(self, name):
        return None

    def scroll_into_view_if_needed(self, timeout=0):
        return None

    def click(self, timeout=0):
        self.clicked += 1
        if self.page and self.name == "Next":
            self.page.step += 1


class Collection:
    def __init__(self, items=()):
        self.items = list(items)
    def count(self):
        return len(self.items)
    @property
    def first(self):
        return self.items[0] if self.items else self
    def nth(self, index):
        return self.items[index]
    def is_visible(self):
        return False
    def is_enabled(self):
        return False


class Body:
    def __init__(self, page):
        self.page = page
    def inner_text(self, timeout=0):
        resume_hint = "Upload resume" if self.page.step == 2 else ""
        return "Apply to Firework %d/6 pages Back Next %s" % (
            self.page.step, resume_hint
        )


class Page:
    url = "https://www.linkedin.com/jobs/view/4461542106/"
    def __init__(self):
        self.step = 1
        self.next_action = Button("Next", self)
        self.back_action = Button("Back")
        self.dismiss_action = Button("Dismiss")
        self.review_action = Button("Review")
        self.required_fields_valid = True
        self.optional_fields_valid = True
        self.optional_probe_values = []

    def locator(self, selector):
        if selector == "body":
            return Body(self)
        if selector == 'button, [role="button"], input[type="button"], input[type="submit"]':
            return Collection([self.dismiss_action, self.back_action, self.next_action])
        if self.step == 5 and selector == "button:text-is('Review')":
            return Collection([self.review_action])
        return Collection()

    def evaluate(self, script, *args):
        if "allowOptionalOnly" in script:
            self.optional_probe_values.append(args)
            allow_optional = args[0] if args else False
            if self.step == 4:
                return bool(allow_optional and self.optional_fields_valid)
            return bool(self.required_fields_valid)
        if "checkValidity()" in script:
            return self.step == 1
        return None

    def wait_for_timeout(self, ms):
        pass


class OptionalWizardNavigationTests(unittest.TestCase):
    def test_four_verified_next_transitions_stop_before_review(self):
        page = Page()
        plans = [
            FillPlan(can_fill=True, reasons=("live_submission_disabled",))
            for _ in range(5)
        ]
        with patch("application_flow.build_page_fill_plan", side_effect=plans), \
             patch("application_flow.apply_fill_plan", return_value=("live_submission_disabled",)), \
             patch("application_flow._easy_apply_progress",
                   side_effect=lambda page: "%d/6 pages" % page.step), \
             patch("application_flow._wait_for_step_transition", return_value=True), \
             patch("application_flow._blocking_confirmation_dialog", return_value=""), \
             patch("application_flow._application_step_signature", return_value=""), \
             patch("application_flow.trace_event") as event:
            result = run_safe_application_flow(
                page, {}, advance=True, inspect_review=False,
                verified_easy_apply_modal=True,
                live_submission_enabled=False,
            )
        self.assertEqual(result.state, "REVIEW_READY")
        self.assertEqual(result.steps_completed, 4)
        self.assertEqual(page.step, 5)
        self.assertEqual(page.next_action.clicked, 4)
        self.assertEqual(page.review_action.clicked, 0)
        self.assertIn((True,), page.optional_probe_values)
        self.assertTrue(any(
            call.args[0] == "next_control_dom_fallback"
            and call.kwargs.get("context") == "verified_wizard"
            and call.kwargs.get("progress") == "4/6 pages"
            for call in event.call_args_list
        ))

    def test_optional_only_requires_prior_confirmed_progress(self):
        page = Page()
        page.step = 4
        with patch("application_flow._easy_apply_progress", return_value="4/6 pages"), \
             patch("application_flow._valid_contact_phone_step", return_value=False):
            for completed in (0, 1, 2, 4):
                with self.subTest(completed=completed):
                    button, _ = _progress_scoped_next(
                        page, verified_contact_modal=True,
                        confirmed_steps_completed=completed,
                    )
                    self.assertIsNone(button)
        self.assertEqual(page.next_action.clicked, 0)
        self.assertNotIn((True,), page.optional_probe_values)

    def test_invalid_optional_control_blocks_fallback(self):
        page = Page()
        page.step = 4
        page.optional_fields_valid = False
        with patch("application_flow._easy_apply_progress", return_value="4/6 pages"), \
             patch("application_flow._valid_contact_phone_step", return_value=False):
            button, _ = _progress_scoped_next(
                page, verified_contact_modal=True,
                confirmed_steps_completed=3,
            )
        self.assertIsNone(button)
        self.assertEqual(page.next_action.clicked, 0)
        self.assertIn((True,), page.optional_probe_values)

    def test_zero_visible_fields_does_not_validate_as_optional_step(self):
        class NoFields(Page):
            def evaluate(self, script, *args):
                return False
        page = NoFields()
        self.assertFalse(_validated_required_wizard_fields(page, allow_optional_only=True))

    def test_unverified_entry_cannot_use_optional_skip(self):
        page = Page()
        page.step = 4
        with patch("application_flow._easy_apply_progress", return_value="4/6 pages"), \
             patch("application_flow._valid_contact_phone_step", return_value=False):
            button, _ = _progress_scoped_next(
                page, verified_contact_modal=False,
                confirmed_steps_completed=3,
            )
        self.assertIsNone(button)

    def test_submitting_action_not_inferred_from_optional_step(self):
        page = Page()
        page.step = 4
        page.next_action.name = "Submit application"
        with patch("application_flow._easy_apply_progress", return_value="4/6 pages"), \
             patch("application_flow._valid_contact_phone_step", return_value=False):
            button, _ = _progress_scoped_next(
                page, verified_contact_modal=True,
                confirmed_steps_completed=3,
            )
        self.assertIsNone(button)
        self.assertEqual(page.next_action.clicked, 0)


if __name__ == "__main__":
    unittest.main()
