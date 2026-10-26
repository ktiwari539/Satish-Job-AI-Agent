"""A local language model is opt-in QA only; never silently enables Submit."""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from job_agent_cli import _run
from grounded_reasoner import configure_local_reasoner


class LocalModelCliTests(unittest.TestCase):
    def tearDown(self):
        configure_local_reasoner("")

    def test_model_rejected_for_live_submit_attempt(self):
        args = SimpleNamespace(
            local_model="qwen2.5:7b",
            debug_easy_apply_only=True,
            approve_one_live_application=True,
            testing_mode=False,
        )
        with patch("job_agent_cli.trace_event"), \
             patch("grounded_reasoner.configure_local_reasoner") as model, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = _run(args)
        self.assertEqual(code, 2)
        self.assertIn("local_reasoner_debug_only", output.getvalue())
        model.assert_not_called()

    def test_model_rejected_without_debug(self):
        args = SimpleNamespace(local_model="qwen2.5:7b",
                               debug_easy_apply_only=False,
                               approve_one_live_application=False,
                               testing_mode=False)
        with patch("job_agent_cli.trace_event"), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            code = _run(args)
        self.assertEqual(code, 2)
        self.assertIn("local_reasoner_debug_only", output.getvalue())

    def test_model_configured_for_non_submitting_queue(self):
        args = SimpleNamespace(
            local_model="qwen2.5:7b",
            debug_easy_apply_only=True, approve_one_live_application=False,
            testing_mode=False, smart_debug=True, smart_debug_queue=True,
        )
        with patch("job_agent_cli.trace_event") as trace, \
             patch("smart_debug_queue.debug_easy_apply_queue", return_value=4) as queue, \
             patch("grounded_reasoner.configure_local_reasoner") as config:
            code = _run(args)
        self.assertEqual(code, 4)
        config.assert_called_once_with("qwen2.5:7b")
        queue.assert_called_once_with(args)
        self.assertTrue(any(call.args[0] == "local_reasoner_enabled"
                            for call in trace.call_args_list))


if __name__ == "__main__":
    unittest.main()
