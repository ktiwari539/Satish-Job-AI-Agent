"""Live submission must verify entered values persisted; no answer values in logs."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from application_forms import FillPlan
from browser_form_runtime import (
    _FORM_READBACK_PROBE, apply_fill_plan, verify_filled_form_values,
)
from application_flow import run_safe_application_flow


class ReadbackPage:
    url = "https://www.linkedin.com/jobs/view/4461542106/"

    def __init__(self, failures=None):
        self.failures = [0] if failures is None else failures
        self.calls = []
        self.target = Input()

    def evaluate(self, script, rows):
        self.calls.append(rows)
        if isinstance(self.failures, Exception):
            raise self.failures
        return self.failures

    def wait_for_timeout(self, ms):
        pass

    def locator(self, selector):
        return self.target


class Input:
    def __init__(self):
        self.first = self
        self.filled = []

    def count(self):
        return 1

    def evaluate(self, script):
        return "input"

    def get_attribute(self, key):
        return "text" if key == "type" else None

    def fill(self, value):
        self.filled.append(value)


class ReadbackSafetyTests(unittest.TestCase):
    def test_probe_checks_text_radio_select_checkbox_without_returning_values(self):
        self.assertIn("field.value", _FORM_READBACK_PROBE)
        self.assertIn("checked.length === 1", _FORM_READBACK_PROBE)
        self.assertIn("field.selectedIndex", _FORM_READBACK_PROBE)
        self.assertIn("field.checked === shouldCheck", _FORM_READBACK_PROBE)
        self.assertIn("return failures", _FORM_READBACK_PROBE)
        self.assertNotIn("document.body.innerText", _FORM_READBACK_PROBE)

    def test_verified_values_continue_without_log_content(self):
        page = ReadbackPage([])
        result = verify_filled_form_values(
            page, {"email": "private@example.com", "salary": "812345"}
        )
        self.assertEqual(result, ())
        self.assertEqual(len(page.calls), 1)

    def test_mismatched_values_fail_with_indices_only(self):
        page = ReadbackPage([1, 0, 1])
        result = verify_filled_form_values(
            page, {"email": "private@example.com", "salary": "812345"}
        )
        self.assertEqual(result, ("field_value_unverified:0", "field_value_unverified:1"))
        self.assertNotIn("private@example.com", str(result))
        self.assertNotIn("812345", str(result))

    def test_unavailable_or_invalid_evidence_fails_closed(self):
        for response, expected in (
            (ValueError("no browser"), "form_readback_unavailable"),
            (True, "form_readback_invalid"),
            ([100], "form_readback_invalid"),
            (["private@example.com"], "form_readback_invalid"),
        ):
            with self.subTest(response=response):
                result = verify_filled_form_values(
                    ReadbackPage(response), {"email": "private@example.com"}
                )
                self.assertEqual(result, (expected,))

    def test_zero_known_fields_do_not_require_readback(self):
        page = ReadbackPage([0])
        self.assertEqual(verify_filled_form_values(page, {}), ())
        self.assertEqual(page.calls, [])

    def test_live_fill_path_detects_unpersisted_values(self):
        page = ReadbackPage([0])
        plan = FillPlan(values={"email": "private@example.com"}, can_fill=True)
        failures = apply_fill_plan(page, plan, verify_readback=True)
        self.assertEqual(failures, ("field_value_unverified:0",))
        self.assertEqual(page.target.filled, ["private@example.com"])

    def test_offline_fill_does_not_require_readback(self):
        page = ReadbackPage([0])
        plan = FillPlan(values={"email": "private@example.com"}, can_fill=True)
        failures = apply_fill_plan(page, plan)
        self.assertEqual(failures, ())
        self.assertEqual(page.calls, [])

    def test_non_submitting_advance_still_verifies_answers(self):
        page = ReadbackPage([0])
        plan = FillPlan(values={"email": "private@example.com"}, can_fill=True)
        with patch("application_flow.build_page_fill_plan", return_value=plan), \
             patch("application_flow._blocking_confirmation_dialog", return_value=""), \
             patch("application_flow.inspect_easy_apply_state"), \
             patch("application_flow._visible_action") as actions:
            result = run_safe_application_flow(
                page, {"email": "private@example.com"},
                live_submission_enabled=False, advance=True,
                inspect_review=False,
            )
        self.assertEqual(result.state, "BLOCKED_AFTER_FILL")
        self.assertIn("field_value_unverified:0", result.reasons)
        actions.assert_not_called()

    def test_live_mismatch_blocks_before_review_or_submit(self):
        page = ReadbackPage([0])
        plan = FillPlan(values={"email": "private@example.com"}, can_fill=True)
        with patch("application_flow.build_page_fill_plan", return_value=plan), \
             patch("application_flow._blocking_confirmation_dialog", return_value=""), \
             patch("application_flow.inspect_easy_apply_state"), \
             patch("application_flow._visible_action") as actions:
            result = run_safe_application_flow(
                page, {"email": "private@example.com"},
                live_submission_enabled=True, advance=True, inspect_review=True
            )
        self.assertEqual(result.state, "BLOCKED_AFTER_FILL")
        self.assertIn("field_value_unverified:0", result.reasons)
        actions.assert_not_called()


if __name__ == "__main__":
    unittest.main()
