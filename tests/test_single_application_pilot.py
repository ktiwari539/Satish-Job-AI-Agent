import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from application_runner import ApplicationAttempt, run_application_batch
from job_agent_cli import _run, _pilot_result, _pilot_job_counts
from models import CandidateProfile, Job
from submission_engine import SubmissionResult


PROFILE = CandidateProfile.from_dict({
    "target_roles": ["customer success manager"],
    "skills": ["customer success", "sla", "stakeholder management", "onboarding"],
    "skill_taxonomy": ["customer success", "sla", "stakeholder management", "onboarding"],
    "preferred_locations": ["india"],
    "remote_allowed": True,
    "total_experience_years": 8,
    "india_authorized": True,
    "outside_india_sponsorship_required": True,
})
POLICY = SimpleNamespace(
    live_submission_enabled=True, duplicate_cooldown_days=90, threshold=75
)


class Store:
    def is_recent_similar_application(self, job, cooldown_days=90):
        return False


def jobs():
    return [Job(
        source="linkedin", external_id=str(i), company="Employer " + str(i),
        title="Customer Success Manager", location="India",
        url="https://www.linkedin.com/jobs/view/" + str(i),
        description=("Customer success SLA stakeholder management onboarding. " * 8),
        required_skills=("customer success", "sla", "stakeholder management", "onboarding"),
        minimum_years=3,
    ) for i in range(3)]


def run_once(apply):
    return run_application_batch(
        jobs(), profile=PROFILE, private_profile={},
        policy=POLICY, store=Store(),
        enrich_job=lambda job: SimpleNamespace(enriched=True, job=job),
        apply_job=apply,
        allow_outside_window=True,
        max_application_attempts=1,
    )


class SingleApplicationPilotTests(unittest.TestCase):
    def test_blocks_all_live_runs_without_explicit_pilot_approval(self):
        with patch("job_agent_cli._load_json", side_effect=AssertionError("credentials or private profile accessed")):
            with patch("job_agent_cli.trace_event"):
                result = _run(SimpleNamespace(approve_one_live_application=False))
        self.assertEqual(result, 3)

    def test_first_blocked_attempt_stops_without_trying_next_job(self):
        called = []
        def apply(job, private):
            called.append(job.external_id)
            return ApplicationAttempt(state="BLOCKED", reason="unconfirmed")
        result = run_once(apply)
        self.assertEqual(called, ["0"])
        self.assertEqual(result.attempted, 1)
        self.assertEqual(result.confirmed, 0)
        self.assertEqual(result.status, "pilot_attempt_limit_reached")

    def test_exception_after_possible_click_stops_without_retry(self):
        called = []
        def apply(job, private):
            called.append(job.external_id)
            raise TimeoutError("post-click navigation timed out")
        result = run_once(apply)
        self.assertEqual(called, ["0"])
        self.assertEqual(result.attempted, 1)
        self.assertEqual(result.blocked, 1)
        self.assertEqual(result.status, "pilot_attempt_limit_reached")

    def test_confirmed_first_job_stops_and_records_once(self):
        called = []
        def apply(job, private):
            called.append(job.external_id)
            return ApplicationAttempt(
                state="CONFIRMED", confirmed=True,
                submission=SubmissionResult(
                    state="CONFIRMED", confirmed=True,
                    evidence="post-submit success dialog",
                ),
            )
        with patch("application_runner.record_confirmed_submission", return_value=True) as recorder:
            result = run_once(apply)
        self.assertEqual(called, ["0"])
        self.assertEqual(result.attempted, 1)
        self.assertEqual(result.confirmed, 1)
        self.assertEqual(result.status, "pilot_attempt_limit_reached")
        recorder.assert_called_once()

    def test_zero_limit_fails_before_any_application(self):
        invoked = []
        result = run_application_batch(
            jobs(), profile=PROFILE, private_profile={},
            policy=POLICY, store=Store(),
            enrich_job=lambda j: SimpleNamespace(enriched=True, job=j),
            apply_job=lambda j, p: invoked.append(j),
            allow_outside_window=True,
            max_application_attempts=0,
        )
        self.assertEqual(result.status, "invalid_attempt_limit")
        self.assertEqual(invoked, [])

    def test_unconfirmed_pilot_returns_failure_even_after_attempt_limit(self):
        for confirmations in (0, 2, 100):
            with self.subTest(confirmations=confirmations):
                status, code = _pilot_result(confirmations)
                self.assertEqual(status, "pilot_unconfirmed")
                self.assertEqual(code, 5)

    def test_only_one_confirmed_pilot_returns_success(self):
        status, code = _pilot_result(1)
        self.assertEqual(status, "pilot_confirmed")
        self.assertEqual(code, 0)

    def test_discovered_counts_distinguish_search_results_and_considered(self):
        result = _pilot_job_counts(7, 1)
        self.assertEqual(result, {"discovered": 7, "considered": 1})
        with self.assertRaises(ValueError):
            _pilot_job_counts(1, 7)

    def test_approval_flag_parse(self):
        with patch.object(sys, "argv", ["job_agent_cli.py", "--approve-one-live-application"]):
            from job_agent_cli import parse_args
            self.assertTrue(parse_args().approve_one_live_application)


if __name__ == "__main__":
    unittest.main()
