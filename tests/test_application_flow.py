import unittest
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from application_flow import run_safe_application_flow
from application_forms import FillPlan


class FakeAction:
    def __init__(self):
        self.clicked = False

    def count(self):
        return 1

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def click(self, timeout=0):
        self.clicked = True


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


class FakePage:
    url = "https://www.linkedin.com/jobs/view/1/"

    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def locator(self, selector):
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
