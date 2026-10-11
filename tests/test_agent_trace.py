import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_trace import RunTracer, reset_active_tracer, set_active_tracer, trace_event, trace_step
from agent_status import _suggest


class AgentTraceTests(unittest.TestCase):
    def test_trace_persists_steps_and_redacts_sensitive_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_dir = Path(tmp) / "agent_runs"
            tracer = RunTracer(
                str(trace_dir),
                heartbeat_seconds=60,
                print_events=False,
            )
            token = set_active_tracer(tracer)
            try:
                tracer.start()
                with trace_step("search"):
                    trace_event(
                        "search_ready",
                        job_count=3,
                        password="never-write-this",
                        access_token="never-write-token",
                    )
                tracer.finish("completed", exit_code=0)
            finally:
                reset_active_tracer(token)

            events = [
                json.loads(line)
                for line in tracer.events_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertTrue(any(event["event"] == "step_start" for event in events))
            ready = next(event for event in events if event["event"] == "search_ready")
            self.assertEqual(ready["job_count"], 3)
            self.assertEqual(ready["password"], "<redacted>")
            self.assertEqual(ready["access_token"], "<redacted>")

            status = json.loads(tracer.status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["run_id"], tracer.run_id)
            self.assertTrue(Path(status["events_file"]).exists())

    def test_status_suggestions_cover_common_application_blockers(self):
        self.assertIn("mandatory application fact", _suggest("BLOCKED_UNKNOWN_REQUIRED_FIELDS"))
        self.assertIn("page transition", _suggest("NEXT_NO_TRANSITION"))
        self.assertIn("external ATS", _suggest("FORM_NOT_READY"))


if __name__ == "__main__":
    unittest.main()
