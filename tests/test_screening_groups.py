"""Screening questions are employer prompts, not individual styled radio labels."""
import sys
import unittest
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screening_groups import (
    _GROUPS_JS, ScreeningResult, inspect_screening_groups,
    answer_verified_screening_groups,
)
from application_flow import run_safe_application_flow
from application_forms import FillPlan


QUESTION = "Do you have at least 10 years of overall experience?"
OTHER = "Are you willing to work evening shifts?"


class ScreeningGroupsTests(unittest.TestCase):
    def test_native_or_styled_yes_no_answer_is_verified_and_never_guessed(self):
        page = MagicMock()
        calls = []
        def evaluate(js, command):
            calls.append(command)
            if command["action"] == "scan":
                return [{
                    "index": 0, "question": QUESTION,
                    "options": ["Yes", "No"], "required": True,
                    "selected": False, "keys": ["opinionAnswer", "radioNo"],
                }]
            if command["action"] in ("prepare", "verify"):
                self.assertEqual(command["question"], QUESTION)
                self.assertEqual(command["answer"], "No")
                return {"status": "prepared" if command["action"] == "prepare"
                        else "confirmed"}
            self.fail("unexpected browser command")
        page.evaluate.side_effect = evaluate
        result = answer_verified_screening_groups(
            page, {"experience_years": "8"}
        )
        self.assertEqual(result.groups_found, 1)
        self.assertEqual(result.choices_confirmed, 1)
        self.assertEqual(result.unresolved_questions, ())
        self.assertEqual(result.answered_field_keys, ("opinionAnswer", "radioNo"))
        self.assertEqual([c["action"] for c in calls], [
            "scan", "prepare", "verify"
        ])
        page.locator.return_value.click.assert_called_once_with(timeout=2000)
        self.assertNotIn(QUESTION, repr(result.answered_questions))

    def test_missing_candidate_fact_does_not_choose_no(self):
        page = MagicMock()
        page.evaluate.return_value = [{
            "index": 0, "question": QUESTION, "options": ["Yes", "No"],
            "required": True, "selected": False,
        }]
        result = answer_verified_screening_groups(page, {})
        self.assertEqual(result.choices_confirmed, 0)
        self.assertEqual(result.unresolved_questions, (QUESTION,))
        page.evaluate.assert_called_once()

    def test_unverifiable_click_blocks_even_with_verified_fact(self):
        page = MagicMock()
        page.evaluate.side_effect = [
            [{"index": 0, "question": QUESTION, "options": ["Yes", "No"],
              "required": True, "selected": False, "keys": ["opinion"]}],
            {"status": "prepared"},
            {"status": "unverified"},
        ]
        result = answer_verified_screening_groups(page, {
            "answers": {QUESTION: "No"},
        })
        self.assertEqual(result.verification_failures, 1)
        self.assertEqual(result.choices_confirmed, 0)
        self.assertEqual(result.unresolved_questions, (QUESTION,))

    def test_selected_question_is_not_trusted_without_profile_fact(self):
        page = MagicMock()
        page.evaluate.return_value = [{
            "index": 0, "question": OTHER, "options": ["Yes", "No"],
            "required": False, "selected": True, "keys": ["shiftChoice"],
        }]
        result = answer_verified_screening_groups(page, {})
        self.assertEqual(result.choices_confirmed, 0)
        self.assertEqual(result.unresolved_questions, (OTHER,))
        page.evaluate.assert_called_once()

    def test_correct_prefilled_choice_verified_without_new_click(self):
        page = MagicMock()
        page.evaluate.side_effect = [
            [{"index": 0, "question": OTHER, "options": ["Yes", "No"],
              "required": True, "selected": True, "keys": ["shiftChoice"]}],
            {"status": "confirmed"},
        ]
        result = answer_verified_screening_groups(page, {
            "answers": {OTHER: "No"},
        })
        self.assertEqual(result.choices_confirmed, 1)
        self.assertEqual(result.answered_field_keys, ("shiftChoice",))
        page.locator.assert_not_called()
        self.assertEqual(page.evaluate.call_count, 2)

    def test_unscoped_form_fails_closed(self):
        page = MagicMock()
        page.evaluate.return_value = []
        result = answer_verified_screening_groups(page, {
            "answers": {QUESTION: "No"},
        })
        self.assertEqual(result.groups_found, 0)
        self.assertEqual(result.choices_confirmed, 0)

    def test_javascript_scopes_to_easy_apply_and_requires_checked_readback(self):
        self.assertIn(".jobs-easy-apply-content", _GROUPS_JS)
        self.assertIn("document.querySelectorAll", _GROUPS_JS)
        self.assertIn("const root = dialogs[0] || inline[0]", _GROUPS_JS)
        self.assertIn("matches.some(selected) ? 'confirmed'", _GROUPS_JS)
        self.assertIn("data-agent-screening-click", _GROUPS_JS)
        self.assertIn("name ? 'name:' + name : group", _GROUPS_JS)
        self.assertNotIn(".submit(", _GROUPS_JS)

    def test_in_browser_screening_script_has_valid_javascript_syntax(self):
        if not shutil.which("node"):
            self.skipTest("Node.js unavailable for JavaScript syntax check")
        run = subprocess.run(
            ["node", "--check"],
            input=_GROUPS_JS, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=10, check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_flow_unknown_group_blocks_before_normal_plan_and_navigation(self):
        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/4482424610/"
        result = ScreeningResult(
            groups_found=1,
            unresolved_questions=(OTHER,),
            verification_failures=0,
        )
        with patch("application_flow.answer_verified_screening_groups",
                   return_value=result), \
             patch("application_flow.build_page_fill_plan",
                   return_value=FillPlan(
                       values={}, can_fill=True,
                       reasons=("live_submission_disabled",),
                   )) as plan, \
             patch("application_flow.apply_fill_plan") as fill, \
             patch("application_flow.inspect_easy_apply_state"), \
             patch("application_flow._blocking_confirmation_dialog",
                   return_value=""), \
             patch("application_flow.trace_event") as trace:
            outcome = run_safe_application_flow(
                page, {}, verified_easy_apply_modal=True, advance=True,
            )
        self.assertEqual(outcome.state, "BLOCKED_UNKNOWN_REQUIRED_FIELDS")
        self.assertEqual(outcome.unknown_required_fields, (OTHER,))
        plan.assert_called_once()
        fill.assert_not_called()
        audit = next(c.kwargs for c in trace.call_args_list
                     if c.args[0] == "verified_screening_group_audit")
        self.assertEqual(audit["unresolved_count"], 1)
        self.assertFalse(audit["question_text_logged"])
        self.assertNotIn(OTHER, repr(audit))

    def test_verified_groups_are_excluded_from_second_radio_fill(self):
        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/4482424610/"
        plan = FillPlan(values={}, can_fill=False, reasons=("live_submission_disabled",))
        result = ScreeningResult(
            groups_found=1, choices_confirmed=1,
            answered_field_keys=("answerField",),
        )
        with patch("application_flow.answer_verified_screening_groups",
                   return_value=result), \
             patch("application_flow.build_page_fill_plan",
                   return_value=plan) as build, \
             patch("application_flow.inspect_easy_apply_state"), \
             patch("application_flow._blocking_confirmation_dialog",
                   return_value=""), \
             patch("application_flow.trace_event"):
            run_safe_application_flow(
                page, {}, verified_easy_apply_modal=True, advance=True,
            )
        self.assertEqual(
            build.call_args.kwargs["verified_choice_keys"], ("answerField",)
        )


if __name__ == "__main__":
    unittest.main()
