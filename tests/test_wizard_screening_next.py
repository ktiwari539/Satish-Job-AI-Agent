"""Regression for Firework Easy Apply page 3/6: eligible Next was skipped."""
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


class Control:
    def __init__(self, label):
        self.label = label
        self.clicked = False
    def is_visible(self):
        return True
    def is_enabled(self):
        return True
    def inner_text(self, timeout=0):
        return self.label
    def get_attribute(self, key):
        return None
    def scroll_into_view_if_needed(self, timeout=0):
        pass
    def click(self, timeout=0):
        self.clicked = True


class Collection:
    def __init__(self, items=()):
        self.items = list(items)
    def count(self):
        return len(self.items)
    @property
    def first(self):
        return self.items[0] if self.items else self
    def nth(self, i):
        return self.items[i]
    def is_visible(self):
        return False
    def is_enabled(self):
        return False


class Body:
    def inner_text(self, timeout=0):
        return "Apply to Firework 3/6 pages Employment history Back Next"


class Page:
    url = "https://www.linkedin.com/jobs/view/4461542106/"
    def __init__(self, candidates):
        self.candidates = candidates
        self.eval_result = True
    def locator(self, selector):
        if selector == "body":
            return Body()
        if selector == 'button, [role="button"], input[type="button"], input[type="submit"]':
            return Collection(self.candidates)
        return Collection()
    def evaluate(self, script):
        return self.eval_result
    def wait_for_timeout(self, ms):
        pass


class ScreeningNavigationTests(unittest.TestCase):
    def test_real_three_of_six_log_pattern_advances_one_safe_next(self):
        next_control = Control("Next")
        page = Page([Control("Dismiss"), Control("Back"), next_control])
        plans = [
            FillPlan(values={"employment_years": "verified"}, can_fill=True,
                     reasons=("live_submission_disabled",)),
            FillPlan(can_fill=False, unknown_required_fields=("Unanswered screening",)),
        ]
        with patch("application_flow.build_page_fill_plan", side_effect=plans), \
             patch("application_flow.apply_fill_plan", return_value=("live_submission_disabled",)), \
             patch("application_flow._easy_apply_progress", return_value="3/6 pages"), \
             patch("application_flow._wait_for_step_transition", return_value=True), \
             patch("application_flow._blocking_confirmation_dialog", return_value=""), \
             patch("application_flow._valid_contact_phone_step", return_value=False), \
             patch("application_flow.trace_event") as trace:
            outcome = run_safe_application_flow(
                page, {}, advance=True, inspect_review=False,
                live_submission_enabled=False, verified_easy_apply_modal=True,
            )
        self.assertTrue(next_control.clicked)
        self.assertEqual(outcome.steps_completed, 1)
        self.assertEqual(outcome.state, "BLOCKED_UNKNOWN_REQUIRED_FIELDS")
        self.assertTrue(any(
            x.args[0] == "next_control_dom_fallback"
            and x.kwargs.get("context") == "verified_wizard"
            for x in trace.call_args_list
        ))

    def test_no_verified_easy_apply_entry_never_clicks_global_next(self):
        next_control = Control("Next")
        page = Page([next_control])
        with patch("application_flow._easy_apply_progress", return_value="3/6 pages"), \
             patch("application_flow._valid_contact_phone_step", return_value=False):
            resolved, action = _progress_scoped_next(
                page, verified_contact_modal=False
            )
        self.assertIsNone(resolved)
        self.assertEqual(action, "")
        self.assertFalse(next_control.clicked)

    def test_invalid_or_missing_required_answer_blocks_next(self):
        next_control = Control("Next")
        page = Page([next_control])
        page.eval_result = False
        with patch("application_flow._easy_apply_progress", return_value="3/6 pages"), \
             patch("application_flow._valid_contact_phone_step", return_value=False):
            resolved, action = _progress_scoped_next(
                page, verified_contact_modal=True
            )
        self.assertIsNone(resolved)
        self.assertEqual(action, "")
        self.assertFalse(next_control.clicked)

    def test_rejects_multiple_next_controls(self):
        page = Page([Control("Next"), Control("Next")])
        with patch("application_flow._easy_apply_progress", return_value="3/6 pages"), \
             patch("application_flow._valid_contact_phone_step", return_value=False):
            resolved, action = _progress_scoped_next(
                page, verified_contact_modal=True
            )
        self.assertIsNone(resolved)
        self.assertEqual(action, "")
        self.assertFalse(any(button.clicked for button in page.candidates))

    def test_last_page_and_submit_controls_never_selected(self):
        for progress in ("6/6 pages", "3/3 pages"):
            for labels in (["Next"], ["Submit application"]):
                page = Page([Control(x) for x in labels])
                with self.subTest(progress=progress, labels=labels), \
                     patch("application_flow._easy_apply_progress", return_value=progress):
                    resolved, action = _progress_scoped_next(
                        page, verified_contact_modal=True
                    )
                self.assertIsNone(resolved)
                self.assertEqual(action, "")
                self.assertFalse(any(item.clicked for item in page.candidates))

    def test_field_validity_check_returns_only_boolean_and_fails_closed(self):
        page = Page([])
        self.assertTrue(_validated_required_wizard_fields(page))
        page.eval_result = {"value": "private-data", "phone": "sensitive"}
        self.assertFalse(_validated_required_wizard_fields(page))


if __name__ == "__main__":
    unittest.main()
