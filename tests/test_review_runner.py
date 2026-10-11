import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models import CandidateProfile, Job
from review_runner import ReviewPreparationResult, prepare_review_batch
from store import JobStore


PROFILE = CandidateProfile(
    target_roles=("customer success manager",),
    skills=("customer success", "sla", "onboarding"),
    preferred_locations=("india",),
    remote_allowed=True,
    total_experience_years=8,
    india_authorized=True,
    outside_india_sponsorship_required=True,
    skill_taxonomy=("customer success", "sla", "onboarding"),
)


@dataclass(frozen=True)
class Enrichment:
    job: Job
    enriched: bool
    reason: str = ""


def qualified_job(external_id="1", *, title="Customer Success Manager", description=""):
    if not description:
        description = (
            "Customer success onboarding SLA stakeholder management retention "
            "customer success onboarding SLA stakeholder management retention "
            "customer success onboarding SLA stakeholder management retention "
            "customer success onboarding SLA stakeholder management retention"
        )
    return Job(
        "linkedin",
        external_id,
        "Example",
        title,
        "Mumbai, India",
        f"https://linkedin.invalid/{external_id}",
        description,
        required_skills=("customer success", "sla", "onboarding"),
        minimum_years=5,
        remote=False,
    )


class ReviewRunnerTests(unittest.TestCase):
    def test_qualified_job_reaches_review_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            job = qualified_job()
            result = prepare_review_batch(
                [job],
                profile=PROFILE,
                private_profile={"email": "candidate@example.invalid"},
                threshold=75,
                cooldown_days=90,
                store=store,
                enrich_job=lambda value: Enrichment(value, True),
                prepare_job=lambda value, private: ReviewPreparationResult("READY_FOR_REVIEW"),
            )
            self.assertEqual(result.ready_for_review, 1)
            self.assertEqual(result.qualified, 1)
            self.assertEqual(result.outcomes[0].status, "READY_FOR_REVIEW")

    def test_short_or_missing_jd_is_skipped_before_preparation(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            job = qualified_job()
            result = prepare_review_batch(
                [job],
                profile=PROFILE,
                private_profile={},
                threshold=75,
                cooldown_days=90,
                store=store,
                enrich_job=lambda value: Enrichment(value, False, "jd_too_short_or_missing"),
                prepare_job=lambda value, private: calls.append(value),
            )
            self.assertEqual(result.skipped_jd, 1)
            self.assertEqual(calls, [])

    def test_recent_similar_application_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            first = qualified_job("1")
            store.mark_submission_confirmed(first)
            repost = qualified_job("2", title="Senior Customer Success Manager")

            result = prepare_review_batch(
                [repost],
                profile=PROFILE,
                private_profile={},
                threshold=75,
                cooldown_days=90,
                store=store,
                enrich_job=lambda value: Enrichment(value, True),
                prepare_job=lambda value, private: ReviewPreparationResult("READY_FOR_REVIEW"),
            )
            self.assertEqual(result.skipped_duplicate, 1)
            self.assertEqual(result.ready_for_review, 0)

    def test_unqualified_job_never_reaches_form_preparation(self):
        calls = []
        weak = Job(
            "linkedin",
            "3",
            "Example",
            "Software Engineer",
            "Mumbai, India",
            "https://linkedin.invalid/3",
            "Python backend APIs distributed systems",
            required_skills=("python", "kubernetes", "aws"),
            minimum_years=5,
            remote=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            result = prepare_review_batch(
                [weak],
                profile=PROFILE,
                private_profile={},
                threshold=75,
                cooldown_days=90,
                store=store,
                enrich_job=lambda value: Enrichment(value, True),
                prepare_job=lambda value, private: calls.append(value),
            )
            self.assertEqual(result.skipped_unqualified, 1)
            self.assertEqual(calls, [])

    def test_blocked_preparation_is_reported_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            job = qualified_job()
            result = prepare_review_batch(
                [job],
                profile=PROFILE,
                private_profile={},
                threshold=75,
                cooldown_days=90,
                store=store,
                enrich_job=lambda value: Enrichment(value, True),
                prepare_job=lambda value, private: ReviewPreparationResult(
                    "BLOCKED",
                    "unknown_required_field",
                ),
            )
            self.assertEqual(result.blocked, 1)
            self.assertEqual(result.ready_for_review, 0)
            self.assertEqual(result.outcomes[0].reason, "unknown_required_field")


if __name__ == "__main__":
    unittest.main()
