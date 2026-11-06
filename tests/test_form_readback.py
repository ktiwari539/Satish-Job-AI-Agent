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
        self.assertEqual(len(page.calls), 2)

    def test_mismatched_values_fail_with_indices_only(self):
        page = ReadbackPage([1, 0, 1])
        result = verify_filled_form_values(
            page, {"email": "private@example.com", "salary": "812345"}
        )
        self.assertEqual(result, ("field_value_unverified:0", "field_value_unverified:1"))
        self.assertNotIn("private@example.com", str(result))
        self.assertNotIn("812345", str(result))

    def test_one_successful_read_does_not_hide_a_later_reactive_reset(self):
        page=ReadbackPage([])
        with patch.object(page,'evaluate',side_effect=[[],[0],[]]):
            self.assertEqual(verify_filled_form_values(page,{'email':'fixture@example.invalid'}),('field_value_unverified:0',))

    def test_two_stable_reads_after_hydration_establish_retention(self):
        page=ReadbackPage([])
        with patch.object(page,'evaluate',side_effect=[[0],[],[]]):
            self.assertEqual(verify_filled_form_values(page,{'email':'fixture@example.invalid'}),())

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

    def test_radio_resolution_audit_never_logs_question_or_private_values(self):
        from types import SimpleNamespace
        from browser_form_runtime import (
            BrowserFieldSnapshot, build_page_fill_plan,
        )
        class Page:
            def locator(self, selector):
                return self
            def inner_text(self, timeout=0):
                return ""
            def count(self):
                return 0
        fields = (
            BrowserFieldSnapshot(
                key="private@example.com", label="Are you available to work shifts?",
                required=False, field_type="radio", options=("Yes", "No"),
            ),
            BrowserFieldSnapshot(
                key="another_question", label="Yes",
                required=False, field_type="radio", options=("Yes",),
            ),
        )
        with patch("browser_form_runtime.inspect_page_fields",
                   return_value=fields), \
             patch("browser_form_runtime.inspect_form_snapshot",
                   return_value=SimpleNamespace(
                       captcha_present=False, manual_auth_required=False,
                   )), \
             patch("browser_form_runtime.build_fill_plan",
                   return_value=FillPlan(can_fill=True)), \
             patch("browser_form_runtime.trace_event") as trace:
            build_page_fill_plan(Page(), {"answers": {
                "are you available to work shifts": "No"
            }})
        audits = [call.kwargs for call in trace.call_args_list
                  if call.args[0] == "screening_question_resolution_audit"]
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit["unresolved_radio_inputs"], 2)
        self.assertTrue(audit["fields"][0]["question_label_extracted"])
        self.assertFalse(audit["fields"][1]["question_label_extracted"])
        self.assertNotIn("private@example.com", str(audit))
        self.assertNotIn("Are you available", str(audit))
        self.assertNotIn("Yes", str(audit))
        self.assertFalse(audit["contains_answer_values"])

    def test_field_inspection_rejects_malformed_browser_response(self):
        """Unexpected evaluate() data must never crash a live wizard."""
        from browser_form_runtime import inspect_page_fields
        from unittest.mock import MagicMock
        page = MagicMock()
        page.evaluate.return_value = True
        self.assertEqual(inspect_page_fields(page), ())
        page.evaluate.return_value = {"error": "transient"}
        self.assertEqual(inspect_page_fields(page), ())

    def test_page_field_inspection_ignores_hidden_background_inputs(self):
        from browser_form_runtime import inspect_page_fields
        from unittest.mock import MagicMock
        page = MagicMock()
        page.evaluate.return_value = []
        self.assertEqual(inspect_page_fields(page), ())
        source = page.evaluate.call_args.args[0]
        self.assertIn("if (isVisible(el)) return true;", source)
        self.assertIn("['radio', 'checkbox', 'file'].includes(type)", source)
        self.assertIn("Array.from(el.labels || []).some(isVisible)", source)
        self.assertIn("return false;", source)

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
