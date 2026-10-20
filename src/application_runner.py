from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, Mapping, Optional, Tuple

from agent_trace import trace_event, trace_step
from automation_policy import AutomationPolicy
from matcher import score_profile
from models import CandidateProfile, Job
from policy import evaluate_eligibility
from quota import evaluate_application_quota
from store import JobStore
from submission_engine import SubmissionResult, record_confirmed_submission


@dataclass(frozen=True)
class ApplicationAttempt:
    state: str
    confirmed: bool = False
    reason: str = ""
    submission: Optional[SubmissionResult] = None


@dataclass(frozen=True)
class ApplicationOutcome:
    job_key: str
    status: str
    reason: str = ""
    score: int = 0


@dataclass(frozen=True)
class ApplicationRunSummary:
    status: str
    discovered: int = 0
    enriched: int = 0
    qualified: int = 0
    attempted: int = 0
    confirmed: int = 0
    blocked: int = 0
    skipped_duplicate: int = 0
    skipped_unqualified: int = 0
    skipped_ineligible: int = 0
    skipped_jd: int = 0
    outcomes: Tuple[ApplicationOutcome, ...] = field(default_factory=tuple)


def run_application_batch(
    jobs: Iterable[Job],
    *,
    profile: CandidateProfile,
    private_profile: Mapping[str, object],
    policy: AutomationPolicy,
    store: JobStore,
    enrich_job: Callable[[Job], object],
    apply_job: Callable[[Job, Mapping[str, object]], ApplicationAttempt],
    now: Optional[datetime] = None,
    allow_outside_window: bool = False,
    max_application_attempts: Optional[int] = None,
) -> ApplicationRunSummary:
    """Run qualified jobs through submission and count only confirmed success."""
    if not policy.live_submission_enabled:
        return ApplicationRunSummary(status="live_submission_disabled")
    if max_application_attempts is not None and max_application_attempts < 1:
        return ApplicationRunSummary(status="invalid_attempt_limit")

    discovered = enriched_count = qualified = attempted = confirmed = blocked = 0
    skipped_duplicate = skipped_unqualified = skipped_ineligible = skipped_jd = 0
    outcomes = []
    attempts_started = 0

    for raw_job in jobs:
        # Fail closed: an exception after a click may still mean a submission
        # happened. Never retry with a second job during a one-shot pilot.
        if max_application_attempts is not None and attempts_started >= max_application_attempts:
            break
        discovered += 1

        if not allow_outside_window:
            quota = evaluate_application_quota(policy, store, now=now)
            trace_event(
                "quota_check",
                allowed=quota.allowed,
                reason=quota.reason,
                active_window=quota.active_window,
                window_confirmed=quota.window_confirmed,
                daily_confirmed=quota.daily_confirmed,
                remaining_window=quota.remaining_window,
                remaining_day=quota.remaining_day,
            )
            if not quota.allowed:
                return ApplicationRunSummary(
                    status=quota.reason,
                    discovered=discovered,
                    enriched=enriched_count,
                    qualified=qualified,
                    attempted=attempted,
                    confirmed=confirmed,
                    blocked=blocked,
                    skipped_duplicate=skipped_duplicate,
                    skipped_unqualified=skipped_unqualified,
                    skipped_ineligible=skipped_ineligible,
                    skipped_jd=skipped_jd,
                    outcomes=tuple(outcomes),
                )

        try:
            with trace_step("jd_enrichment", job_key=raw_job.key):
                enrichment = enrich_job(raw_job)
        except Exception as exc:
            skipped_jd += 1
            reason = f"jd_enrichment_failed:{type(exc).__name__}"
            trace_event("job_decision", job_key=raw_job.key, decision="SKIPPED_JD", reason=reason)
            outcomes.append(ApplicationOutcome(raw_job.key, "SKIPPED_JD", reason))
            continue

        if not bool(getattr(enrichment, "enriched", False)):
            skipped_jd += 1
            reason = str(getattr(enrichment, "reason", "full_jd_required"))
            trace_event("job_decision", job_key=raw_job.key, decision="SKIPPED_JD", reason=reason)
            outcomes.append(ApplicationOutcome(raw_job.key, "SKIPPED_JD", reason))
            continue

        job = getattr(enrichment, "job", raw_job)
        enriched_count += 1

        if store.is_recent_similar_application(
            job,
            cooldown_days=policy.duplicate_cooldown_days,
        ):
            skipped_duplicate += 1
            outcomes.append(
                ApplicationOutcome(job.key, "SKIPPED_DUPLICATE", "recent_similar_application")
            )
            trace_event(
                "job_decision",
                job_key=job.key,
                decision="SKIPPED_DUPLICATE",
                reason="recent_similar_application",
            )
            continue

        with trace_step("job_scoring", job_key=job.key):
            match = score_profile(profile, job, threshold=policy.threshold)
        trace_event(
            "job_score",
            job_key=job.key,
            score=match.score,
            threshold=policy.threshold,
            decision=match.decision,
            reasons=list(match.reasons),
        )
        if match.decision != "APPLY":
            skipped_unqualified += 1
            outcomes.append(
                ApplicationOutcome(job.key, "SKIPPED_UNQUALIFIED", "score_below_threshold", match.score)
            )
            continue

        with trace_step("eligibility_check", job_key=job.key):
            eligibility = evaluate_eligibility(profile, job)
        trace_event(
            "job_eligibility",
            job_key=job.key,
            eligible=eligibility.eligible,
            reasons=list(eligibility.reasons),
        )
        if not eligibility.eligible:
            skipped_ineligible += 1
            outcomes.append(
                ApplicationOutcome(
                    job.key,
                    "SKIPPED_INELIGIBLE",
                    "|".join(eligibility.reasons),
                    match.score,
                )
            )
            continue

        qualified += 1
        attempts_started += 1
        attempted += 1
        try:
            with trace_step(
                "end_to_end_application",
                job_key=job.key,
                company=job.company,
                title=job.title,
            ):
                attempt = apply_job(job, private_profile)
        except Exception as exc:
            blocked += 1
            reason = f"application_failed:{type(exc).__name__}"
            trace_event("job_decision", job_key=job.key, decision="BLOCKED", reason=reason)
            outcomes.append(ApplicationOutcome(job.key, "BLOCKED", reason, match.score))
            continue

        if (
            attempt.confirmed
            and attempt.submission is not None
            and record_confirmed_submission(store, job, attempt.submission)
        ):
            confirmed += 1
            trace_event(
                "job_decision",
                job_key=job.key,
                decision="CONFIRMED",
                score=match.score,
                evidence=attempt.submission.evidence,
            )
            outcomes.append(ApplicationOutcome(job.key, "CONFIRMED", "", match.score))
        else:
            blocked += 1
            reason = attempt.reason or "application_not_confirmed"
            trace_event(
                "job_decision",
                job_key=job.key,
                decision=attempt.state or "BLOCKED",
                reason=reason,
                score=match.score,
            )
            outcomes.append(
                ApplicationOutcome(
                    job.key,
                    attempt.state or "BLOCKED",
                    reason,
                    match.score,
                )
            )

    if max_application_attempts is not None and attempts_started >= max_application_attempts:
        status = "pilot_attempt_limit_reached"
    elif not allow_outside_window:
        final_quota = evaluate_application_quota(policy, store, now=now)
        if final_quota.reason in {
            "window_success_target_reached",
            "daily_success_cap_reached",
        }:
            status = final_quota.reason
        else:
            status = "JOB_POOL_EXHAUSTED"
    else:
        status = "JOB_POOL_EXHAUSTED"

    return ApplicationRunSummary(
        status=status,
        discovered=discovered,
        enriched=enriched_count,
        qualified=qualified,
        attempted=attempted,
        confirmed=confirmed,
        blocked=blocked,
        skipped_duplicate=skipped_duplicate,
        skipped_unqualified=skipped_unqualified,
        skipped_ineligible=skipped_ineligible,
        skipped_jd=skipped_jd,
        outcomes=tuple(outcomes),
    )
