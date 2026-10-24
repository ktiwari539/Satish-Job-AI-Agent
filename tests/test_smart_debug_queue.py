"""Bounded smart debug queue never submits or retries an ambiguous exact job."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from smart_debug_queue import debug_easy_apply_queue


def args(**changes):
    data = {
        "portal": "linkedin",
        "query": "Customer Success Manager",
        "location": "India",
        "max_jobs": 10,
        "smart_max_forms": 3,
        "job_url": "https://www.linkedin.com/jobs/view/4481663953/",
        "debug_easy_apply_only": True,
        "smart_debug": True,
        "smart_debug_queue": True,
        "debug_interactive": False,
        "debug_hold_seconds": 0,
        "profile_dir": "browser-profile",
        "headless": False,
        "approve_one_live_application": False,
        "allow_outside_window": False,
    }
    data.update(changes)
    return SimpleNamespace(**data)


def job(id, title="Customer Success Manager"):
    return SimpleNamespace(
        title=title,
        url="https://www.linkedin.com/jobs/view/%s/" % id,
        key="linkedin:%s" % id,
    )


class SmartDebugQueueTests(unittest.TestCase):
    def test_continues_after_blocked_job_then_reaches_review_without_submit(self):
        runtime = MagicMock()
        adapter = MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False
        )
        adapter.extract_search_results.return_value = [
            job(4481663953), job(4482424610), job(4482424611),
            job(4482424612),
        ]
        observed = []
        states = [
            ("easy_apply_debug_blocked", "FORM_NOT_READY", 4),
            ("easy_apply_debug_review_reached", "REVIEW_INSPECTED", 0),
            ("debug_portal_already_applied_skipped", "NOT_RUN_ALREADY_APPLIED", 0),
        ]

        def fake_debug(a):
            observed.append(a)
            status, state, code = states[len(observed) - 1]
            print(json.dumps({"status": status, "flow_state": state,
                              "attempted": 0, "confirmed": 0,
                              "submission_enabled": False}))
            return code

        with patch("smart_debug_queue.PlaywrightSession", return_value=runtime), \
             patch("smart_debug_queue.LinkedInBrowserAdapter", return_value=adapter), \
             patch("smart_debug_queue.debug_easy_apply", side_effect=fake_debug), \
             patch("smart_debug_queue.trace_event") as trace, \
             redirect_stdout(io.StringIO()) as out:
            code = debug_easy_apply_queue(args())
        self.assertEqual(code, 0)
        outputs = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(outputs[-1]["checked"], 3)
        self.assertEqual(outputs[-1]["review_reached"], 1)
        # Review reached does not mean resume or submit-selector was verified.
        self.assertEqual(outputs[-1]["release_checks_passed"], 0)
        self.assertEqual(outputs[-1]["ignored_original_job_id"], "4481663953")
        self.assertTrue(outputs[-1]["no_submit_clicks"])
        self.assertEqual(
            [a.job_url for a in observed],
            [job(n).url for n in (4482424610, 4482424611, 4482424612)]
        )
        for a in observed:
            self.assertFalse(a.smart_debug)
            self.assertFalse(a.debug_interactive)
            self.assertFalse(a.approve_one_live_application)
            self.assertEqual(a.debug_hold_seconds, 0)
        self.assertTrue(any(
            call.args[0] == "smart_queue_complete"
            for call in trace.call_args_list
        ))

    def test_limits_to_one_candidate_even_if_search_returns_many(self):
        runtime = MagicMock()
        adapter = MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False
        )
        adapter.extract_search_results.return_value = [
            job(4482424610), job(4482424611), job(4482424612),
        ]
        def fake_debug(a):
            print(json.dumps({"status": "easy_apply_debug_blocked",
                              "flow_state": "FORM_NOT_READY"}))
            return 4
        with patch("smart_debug_queue.PlaywrightSession", return_value=runtime), \
             patch("smart_debug_queue.LinkedInBrowserAdapter", return_value=adapter), \
             patch("smart_debug_queue.debug_easy_apply", side_effect=fake_debug) as debug, \
             patch("smart_debug_queue.trace_event"), \
             redirect_stdout(io.StringIO()) as out:
            code = debug_easy_apply_queue(args(smart_max_forms=1, job_url=""))
        self.assertEqual(code, 4)
        self.assertEqual(debug.call_count, 1)
        self.assertEqual(json.loads(out.getvalue().splitlines()[-1])["checked"], 1)

    def test_interactive_queue_keeps_agent_checkpoint_enabled(self):
        runtime = MagicMock()
        adapter = MagicMock()
        adapter.login_state.return_value = SimpleNamespace(
            authenticated=True, needs_human_action=False
        )
        adapter.extract_search_results.return_value = [job(4482424610)]
        flags = []
        def fake_debug(a):
            flags.append(a.debug_interactive)
            print(json.dumps({
                "status": "easy_apply_debug_blocked",
                "flow_state": "BLOCKED_UNKNOWN_REQUIRED_FIELDS",
                "flow_tested": True,
            }))
            return 4
        with patch("smart_debug_queue.sys.stdin") as terminal, \
             patch("smart_debug_queue.PlaywrightSession", return_value=runtime), \
             patch("smart_debug_queue.LinkedInBrowserAdapter", return_value=adapter), \
             patch("smart_debug_queue.debug_easy_apply", side_effect=fake_debug), \
             patch("smart_debug_queue.trace_event"), \
             redirect_stdout(io.StringIO()) as out:
            terminal.isatty.return_value = True
            code = debug_easy_apply_queue(args(
                job_url="", debug_interactive=True, smart_max_forms=1,
            ))
        self.assertEqual(code, 4)
        self.assertEqual(flags, [True])
        self.assertIn("smart_queue_job_checked", out.getvalue())
        self.assertEqual(
            json.loads(out.getvalue().splitlines()[-1])["blocked_forms"], 1
        )

    def test_interactive_queue_refuses_non_terminal_without_browser(self):
        with patch("smart_debug_queue.sys.stdin") as terminal, \
             patch("smart_debug_queue.PlaywrightSession") as session, \
             redirect_stdout(io.StringIO()) as out:
            terminal.isatty.return_value = False
            result = debug_easy_apply_queue(args(debug_interactive=True))
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(out.getvalue())["status"],
                         "smart_queue_interactive_terminal_required")
        session.assert_not_called()

    def test_refuses_live_approval_and_missing_non_submitting_mode(self):
        for setting, expected in (
            ({"debug_easy_apply_only": False},
             "smart_queue_requires_non_submitting_smart_debug"),
            ({"smart_debug": False},
             "smart_queue_requires_non_submitting_smart_debug"),
            ({"approve_one_live_application": True},
             "smart_queue_live_flags_forbidden"),
        ):
            with self.subTest(setting=setting), \
                 patch("smart_debug_queue.PlaywrightSession") as runtime, \
                 redirect_stdout(io.StringIO()) as out:
                result = debug_easy_apply_queue(args(**setting))
            self.assertEqual(result, 2)
            self.assertEqual(json.loads(out.getvalue())["status"], expected)
            runtime.assert_not_called()


if __name__ == "__main__":
    unittest.main()
