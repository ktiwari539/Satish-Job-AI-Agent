"""Regression: capture useful phone-step evidence before browser closes."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live_blocker_capture import (
    _safe_snapshot, capture_blocker, hold_blocked_browser,
    inspect_easy_apply_state,
)


class Page:
    def __init__(self, data):
        self.data = data
        self.wait_calls = []
        self.eval_calls = 0
        self.clicks = 0
    def evaluate(self, script):
        self.eval_calls += 1
        return self.data
    def wait_for_timeout(self, ms):
        self.wait_calls.append(ms)
    def click(self, *a, **kw):
        self.clicks += 1
        raise AssertionError("diagnostics must not click")


RAW = {
    "progress": "2/4",
    "visible_modal_count": 1,
    "dialog_nodes": 1,
    "form_nodes": 1,
    "body_chars": 10331,
    "input_count": 3,
    "main_frame": True,
    "phone": [{
        "kind": "input", "input_type": "tel", "visible": True,
        "required": True, "empty": False, "invalid": True,
        "disabled": False, "value": "SENSITIVE_PHONE_1234",
        "label": "my private phone",
    }],
    "actions": [{
        "action": "next", "matched": 1, "visible": 1,
        "enabled": 1, "within_modal": 1,
        "label": "my private name",
    }, {"action": "submit", "matched": 0, "visible": 0, "enabled": 0,
        "within_modal": 0}],
    "validation": {
        "invalid_visible": 1, "required_empty_visible": 0,
        "known_required_warning": True,
        "error_text": "Private phone number is incorrect",
    },
    "html": "<private>token and email</private>",
}


class LiveBlockerCaptureTests(unittest.TestCase):
    def test_filter_drops_all_values_labels_html_and_user_data(self):
        result = _safe_snapshot(RAW)
        self.assertEqual(result["progress"], "2/4")
        self.assertEqual(len(result["phone"]), 1)
        self.assertTrue(result["phone"][0]["invalid"])
        self.assertFalse(result["phone"][0]["empty"])
        self.assertEqual(result["actions"][0]["action"], "next")
        self.assertEqual(result["actions"][0]["enabled"], 1)
        rendered = json.dumps(result)
        for private in ("SENSITIVE_PHONE_1234", "my private phone",
                        "my private name", "error_text", "token and email"):
            self.assertNotIn(private, rendered)

    def test_capture_local_file_before_close_without_click(self):
        with tempfile.TemporaryDirectory() as folder:
            fake_trace = SimpleNamespace(trace_dir=folder, run_id="unit-run")
            page = Page(RAW)
            with patch("live_blocker_capture.get_active_tracer", return_value=fake_trace), \
                 patch("live_blocker_capture.trace_event") as event:
                path = capture_blocker(
                    page, stage="live_application_unconfirmed",
                    outcome="NO_SAFE_NEXT_ACTION",
                    reason_code="next_control_not_found:selector",
                    steps_completed=1,
                )
            self.assertEqual(page.clicks, 0)
            self.assertEqual(page.eval_calls, 1)
            self.assertTrue(Path(path).is_file())
            result = json.loads(Path(path).read_text())
            self.assertEqual(result["outcome"], "NO_SAFE_NEXT_ACTION")
            self.assertEqual(result["reason_code"], "next_control_not_found")
            self.assertEqual(result["steps_completed"], 1)
            self.assertEqual(result["snapshot"]["actions"][0]["enabled"], 1)
            self.assertNotIn("SENSITIVE_PHONE_1234", json.dumps(result))
            self.assertEqual(event.call_args.args[0], "application_blocker_captured")
            self.assertEqual(event.call_args.kwargs["report_path"], path)

    def test_before_and_after_snapshot_are_read_only(self):
        page = Page(RAW)
        with patch("live_blocker_capture.trace_event") as event:
            inspect_easy_apply_state(page, stage="before_fill", step_index=0)
            page.data = dict(RAW, phone=[dict(RAW["phone"][0], empty=True)])
            inspect_easy_apply_state(page, stage="after_fill", step_index=0)
        self.assertEqual(page.clicks, 0)
        self.assertEqual(page.eval_calls, 2)
        self.assertEqual(event.call_count, 2)
        self.assertEqual(event.call_args.kwargs["stage"], "after_fill")
        self.assertTrue(event.call_args.kwargs["snapshot"]["phone"][0]["empty"])

    def test_blocked_browser_holds_only_if_requested(self):
        page = Page(RAW)
        with patch("live_blocker_capture.trace_event"):
            hold_blocked_browser(page, 0)
            self.assertEqual(page.wait_calls, [])
            hold_blocked_browser(page, 45)
            self.assertEqual(page.wait_calls, [45000])
            hold_blocked_browser(page, 1000)
            self.assertEqual(page.wait_calls, [45000, 120000])
        self.assertEqual(page.clicks, 0)

    def test_probe_error_fails_closed_without_leaking_content(self):
        page = Page("any page-controlled user text")
        with patch("live_blocker_capture.trace_event"):
            result = inspect_easy_apply_state(page, stage="blocked")
        self.assertEqual(result, {"availability": "browser_probe_failed"})

    def test_untrusted_types_cannot_inject_report_fields(self):
        result = _safe_snapshot({
            "progress": "private-phone-number", "body_chars": "private",
            "actions": [{"action": "untrusted_private_action", "matched": 2}],
            "phone": [{"visible": "false", "empty": "private-user-value"}],
        })
        self.assertNotIn("progress", result)
        self.assertEqual(result["actions"], [])
        self.assertEqual(result["body_chars"], 0)
        self.assertFalse(result["phone"][0]["visible"])
        self.assertFalse(result["phone"][0]["empty"])


if __name__ == "__main__":
    unittest.main()
