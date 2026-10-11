from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Tuple

from agent_trace import trace_event, trace_step
from matcher import score_profile
from models import CandidateProfile, Job
from policy import evaluate_eligibility
from store import JobStore


@dataclass(frozen=True)
class ReviewPreparationResult:
    state: str
    reason: str = ""


@dataclass(frozen=True)
class ReviewOutcome:
    job_key: str
    status: str
    reason: str = ""
    score: int = 0


@dataclass(frozen=True)
class ReviewRunSummary:
    discovered: int = 0
    enriched: int = 0
    qualified: int = 0
    ready_for_review: int = 0
    skipped_duplicate: int = 0
    skipped_unqualified: int = 0
    skipped_ineligible: int = 0
    skipped_jd: int = 0
    blocked: int = 0
    outcomes: Tuple[ReviewOutcome, ...] = field(default_factory=tuple)


def prepare_review_batch(
    jobs: Iterable[Job],
    *,
    profile: CandidateProfile,
    private_profile: Mapping[str, object],
    threshold: int,
    cooldown_days: int,
    store: JobStore,
    enrich_job: Callable[[Job], object],
    prepare_job: Callable[[Job, Mapping[str, object]], ReviewPreparationResult],
) -> ReviewRunSummary:
    """Prepare qualified applications through the review screen only.

    This function deliberately stops before submission. It requires full-JD
    enrichment, score and eligibility gates, and recent-application dedupe.
    """
    discovered = enriched_count = qualified = ready = 0
    skipped_duplicate = skipped_unqualified = skipped_ineligible = skipped_jd = blocked = 0
    outcomes = []

    for raw_job in jobs:
        discovered += 1
        trace_event(
            "job_discovered",
            job_key=raw_job.key,
            company=raw_job.company,
            title=raw_job.title,
            location=raw_job.location,
        )

        try:
            with trace_step(
                "jd_enrichment",
                job_key=raw_job.key,
                company=raw_job.company,
                title=raw_job.title,
            ):
                enrichment = enrich_job(raw_job)
        except Exception as exc:
            skipped_jd += 1
            reason = f"jd_enrichment_failed:{type(exc).__name__}"
            trace_event("job_decision", job_key=raw_job.key, decision="SKIPPED_JD", reason=reason)
            outcomes.append(
                ReviewOutcome(
                    raw_job.key,
                    "SKIPPED_JD",
                    reason,
                )
            )
            continue

        if not bool(getattr(enrichment, "enriched", False)):
            skipped_jd += 1
            reason = str(getattr(enrichment, "reason", "full_jd_required"))
            trace_event("job_decision", job_key=raw_job.key, decision="SKIPPED_JD", reason=reason)
            outcomes.append(
                ReviewOutcome(
                    raw_job.key,
                    "SKIPPED_JD",
                    reason,
                )
            )
            store.mark_seen(raw_job)
            continue

        job = getattr(enrichment, "job", raw_job)
        enriched_count += 1

        if store.is_recent_similar_application(job, cooldown_days=cooldown_days):
            skipped_duplicate += 1
            trace_event(
                "job_decision",
                job_key=job.key,
                decision="SKIPPED_DUPLICATE",
                reason="recent_similar_application",
            )
            outcomes.append(
                ReviewOutcome(job.key, "SKIPPED_DUPLICATE", "recent_similar_application")
            )
            store.mark_seen(job)
            continue

        with trace_step("job_scoring", job_key=job.key):
            match = score_profile(profile, job, threshold=threshold)
        trace_event(
            "job_score",
            job_key=job.key,
            score=match.score,
            threshold=threshold,
            decision=match.decision,
            reasons=list(match.reasons),
        )
        if match.decision != "APPLY":
            skipped_unqualified += 1
            trace_event(
                "job_decision",
                job_key=job.key,
                decision="SKIPPED_UNQUALIFIED",
                reason="score_below_threshold",
                score=match.score,
            )
            outcomes.append(
                ReviewOutcome(
                    job.key,
                    "SKIPPED_UNQUALIFIED",
                    "score_below_threshold",
                    match.score,
                )
            )
            store.mark_seen(job)
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
            trace_event(
                "job_decision",
                job_key=job.key,
                decision="SKIPPED_INELIGIBLE",
                reason="|".join(eligibility.reasons),
            )
            outcomes.append(
                ReviewOutcome(
                    job.key,
                    "SKIPPED_INELIGIBLE",
                    "|".join(eligibility.reasons),
                    match.score,
                )
            )
            store.mark_seen(job)
            continue

        qualified += 1
        trace_event("job_decision", job_key=job.key, decision="QUALIFIED", score=match.score)
        try:
            with trace_step(
                "application_preparation",
                job_key=job.key,
                company=job.company,
                title=job.title,
            ):
                result = prepare_job(job, private_profile)
        except Exception as exc:
            blocked += 1
            reason = f"preparation_failed:{type(exc).__name__}"
            trace_event("job_decision", job_key=job.key, decision="BLOCKED", reason=reason, score=match.score)
            outcomes.append(
                ReviewOutcome(
                    job.key,
                    "BLOCKED",
                    reason,
                    match.score,
                )
            )
            store.mark_seen(job)
            continue

        trace_event(
            "application_preparation_result",
            job_key=job.key,
            state=result.state,
            reason=result.reason,
            score=match.score,
        )
        if result.state == "READY_FOR_REVIEW":
            ready += 1
            outcomes.append(ReviewOutcome(job.key, "READY_FOR_REVIEW", "", match.score))
        else:
            blocked += 1
            outcomes.append(
                ReviewOutcome(
                    job.key,
                    result.state or "BLOCKED",
                    result.reason or "review_not_ready",
                    match.score,
                )
            )
        store.mark_seen(job)

    return ReviewRunSummary(
        discovered=discovered,
        enriched=enriched_count,
        qualified=qualified,
        ready_for_review=ready,
        skipped_duplicate=skipped_duplicate,
        skipped_unqualified=skipped_unqualified,
        skipped_ineligible=skipped_ineligible,
        skipped_jd=skipped_jd,
        blocked=blocked,
        outcomes=tuple(outcomes),
    )
