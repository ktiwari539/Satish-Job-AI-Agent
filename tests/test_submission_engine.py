import unittest
from pathlib import Path
import sys
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from submission_engine import (
    SubmissionResult,
    record_confirmed_submission,
    submit_application,
    submit_linkedin_application,
)


class FakeSubmit:
    def inner_text(self, timeout=0):
        return "Submit application"

    def get_attribute(self, name):
        return ""

    def scroll_into_view_if_needed(self, timeout=0):
        pass

    def click(self, timeout=0):
        pass


class FakePage:
    url = "https://www.linkedin.com/jobs/view/1/"

    def wait_for_timeout(self, value):
        pass


class SubmissionEngineTests(unittest.TestCase):
    def test_roleless_artdeco_modal_is_used_for_submit_selector(self):
        from submission_engine import _active_dialog_root, _visible_submit_control

        class Modal:
            def count(self):
                return 1
            def is_visible(self):
                return True

        class Button:
            def count(self):
                return 1
            def is_visible(self):
                return True
            def is_enabled(self):
                return True

        class Empty:
            def count(self):
                return 0
            def is_visible(self):
                return False
            def is_enabled(self):
                return False

        class Locator:
            def __init__(self, obj):
                self.first = obj

        class RolelessModalPage(FakePage):
            def locator(self, selector):
                if selector == ".artdeco-modal":
                    return Locator(Modal())
                if selector == ".artdeco-modal button:text-is('Submit application')":
                    return Locator(Button())
                return Locator(Empty())

        page = RolelessModalPage()
        self.assertEqual(_active_dialog_root(page), ".artdeco-modal")
        selected, text = _visible_submit_control(page)
        self.assertIsNotNone(selected)
        self.assertEqual(text, "Submit application")

    def test_roleless_modal_alone_never_causes_submission_without_approval(self):
        from submission_engine import _visible_submit_control

        class NoClickPage(FakePage):
            def locator(self, selector):
                raise AssertionError("unapproved submission must not look for controls")

        result = submit_linkedin_application(
            NoClickPage(), live_submission_enabled=False,
            prior_state="SUBMIT_READY",
        )
        self.assertFalse(result.confirmed)
        self.assertEqual(result.state, "SUBMIT_DISABLED")

    def test_live_submission_is_disabled_by_default_gate(self):
        result = submit_linkedin_application(
            FakePage(),
            live_submission_enabled=False,
            prior_state="SUBMIT_READY",
        )
        self.assertEqual(result.state, "SUBMIT_DISABLED")
        self.assertFalse(result.confirmed)

    def test_invalid_prior_state_never_clicks_submit(self):
        with patch("submission_engine._visible_submit_control") as control:
            result = submit_linkedin_application(
                FakePage(),
                live_submission_enabled=True,
                prior_state="REVIEW_READY",
            )
        control.assert_not_called()
        self.assertEqual(result.state, "SUBMIT_BLOCKED")

    def test_review_mismatch_blocks_submission(self):
        result = submit_linkedin_application(
            FakePage(),
            live_submission_enabled=True,
            prior_state="SUBMIT_READY",
            review_mismatches=("phone",),
        )
        self.assertEqual(result.state, "SUBMIT_BLOCKED")
        self.assertEqual(result.reason, "review_mismatch")

    def test_click_without_confirmation_is_not_success(self):
        with patch(
            "submission_engine._visible_submit_control",
            return_value=(FakeSubmit(), "Submit application"),
        ), patch(
            "submission_engine._wait_for_linkedin_confirmation",
            return_value="",
        ):
            result = submit_linkedin_application(
                FakePage(),
                live_submission_enabled=True,
                prior_state="SUBMIT_READY",
            )
        self.assertEqual(result.state, "SUBMIT_UNCONFIRMED")
        self.assertFalse(result.confirmed)

    def test_positive_confirmation_is_required_for_success(self):
        with patch(
            "submission_engine._visible_submit_control",
            return_value=(FakeSubmit(), "Submit application"),
        ), patch(
            "submission_engine._wait_for_linkedin_confirmation",
            return_value="confirmation_dialog:Application submitted",
        ):
            result = submit_linkedin_application(
                FakePage(),
                live_submission_enabled=True,
                prior_state="SUBMIT_READY",
            )
        self.assertEqual(result.state, "CONFIRMED")
        self.assertTrue(result.confirmed)
        self.assertTrue(result.evidence)

    def test_external_submit_requires_positive_confirmation(self):
        with patch(
            "submission_engine._visible_submit_control",
            return_value=(FakeSubmit(), "Submit application"),
        ), patch(
            "submission_engine._wait_for_external_confirmation",
            return_value="external_confirmation:thank you for applying",
        ):
            result = submit_application(
                FakePage(),
                application_type="EXTERNAL_APPLY",
                live_submission_enabled=True,
                prior_state="SUBMIT_READY",
            )
        self.assertTrue(result.confirmed)
        self.assertEqual(result.state, "CONFIRMED")

    def test_external_submit_without_confirmation_is_not_success(self):
        with patch(
            "submission_engine._visible_submit_control",
            return_value=(FakeSubmit(), "Submit application"),
        ), patch(
            "submission_engine._wait_for_external_confirmation",
            return_value="",
        ):
            result = submit_application(
                FakePage(),
                application_type="EXTERNAL_APPLY",
                live_submission_enabled=True,
                prior_state="SUBMIT_READY",
            )
        self.assertFalse(result.confirmed)
        self.assertEqual(result.state, "SUBMIT_UNCONFIRMED")

    def test_ledger_write_requires_confirmed_evidence(self):
        store = Mock()
        job = object()
        unconfirmed = SubmissionResult(state="SUBMIT_UNCONFIRMED")
        self.assertFalse(record_confirmed_submission(store, job, unconfirmed))
        store.mark_submission_confirmed.assert_not_called()

        confirmed = SubmissionResult(
            state="CONFIRMED",
            confirmed=True,
            evidence="confirmation_dialog:Application submitted",
        )
        self.assertTrue(record_confirmed_submission(store, job, confirmed))
        store.mark_submission_confirmed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
