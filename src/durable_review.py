"""Run the existing qualification/preparation pipeline through durable leases."""
from dataclasses import asdict, is_dataclass

from application_queue import QueueError, verified_preparation
from browser_runtime import BrowserRuntimeUnavailable
from jd_enrichment import EnrichmentResult
from review_runner import prepare_review_batch, ReviewPreparationResult, ReviewRunSummary, ReviewOutcome


class PreparationDeferred(Exception):
    pass


def run_durable_review_batch(jobs, *, queue, sources, revision, max_jobs,
                             profile, private_profile, threshold, cooldown_days,
                             enrich_job, prepare_job, control_check=None):
    """Persist new discoveries, resume unfinished work, and never submit.

    PREPARED requires categorical evidence from the actual adapter, not merely
    a legacy READY_FOR_REVIEW string. A control/revision change stops the run.
    """
    if type(max_jobs) is not int or not 1 <= max_jobs <= 100:
        raise QueueError('invalid_worker_limit')
    if not sources: return ReviewRunSummary(), 'no_supported_preparation_sources'
    totals = {name: 0 for name in ReviewRunSummary.__dataclass_fields__ if name != 'outcomes'}
    outcomes = []
    queue.refresh_revision(revision, sources)
    for job in jobs:
        try:
            queue.enqueue(job, revision)
        except QueueError as exc:
            totals['skipped_jd'] += 1
            totals['discovered'] += 1
            outcomes.append(ReviewOutcome(job.key, 'SKIPPED_JD', str(exc)))
    stop = ''

    def check():
        if queue.paused(): return 'queue_paused'
        return control_check() if control_check else ''

    for _ in range(max_jobs):
        stop = check()
        if stop: break
        lease = queue.claim(sources=sources)
        if lease is None: break
        if lease.facts_revision != revision:
            queue.defer(lease, 'current_facts_revision_required')
            stop = 'current_facts_revision_required'
            break
        evidence = {}

        def enrich(job):
            result = enrich_job(job)
            target = getattr(result, 'job', job)
            if (target.source, target.external_id, target.url) != (job.source, job.external_id, job.url):
                return EnrichmentResult(job, False, 'queue_job_identity_changed')
            return result

        def prepare(job, facts):
            reason = check()
            if reason: raise PreparationDeferred(reason)
            queue.eligible(lease, job)
            result = prepare_job(job, facts)
            evidence.update(asdict(result) if is_dataclass(result) else {})
            if result.state == 'READY_FOR_REVIEW' and not verified_preparation(evidence):
                return ReviewPreparationResult('BLOCKED', 'preparation_evidence_incomplete')
            return result

        # The legacy runner contains the shared score, eligibility, cooldown
        # and ledger checks. Defer exceptions must not be swallowed as a job error.
        deferred = []
        def safe_prepare(job, facts):
            try: return prepare(job, facts)
            except PreparationDeferred as exc:
                deferred.append(str(exc))
                return ReviewPreparationResult('DEFERRED', str(exc))
        try:
            result = prepare_review_batch([lease.job], profile=profile, private_profile=private_profile,
                threshold=threshold, cooldown_days=cooldown_days, store=queue.store,
                enrich_job=enrich, prepare_job=safe_prepare)
        except BrowserRuntimeUnavailable:
            queue.finish(lease, 'RETRY_WAIT', 'browser_runtime_unavailable')
            raise
        except BaseException:
            # Abrupt exit leaves a recoverable lease. A submission reservation
            # is never reclaimed by this preparation-only worker.
            raise
        if deferred:
            stop = deferred[0]
            queue.defer(lease, stop)
            break
        outcome = result.outcomes[0]
        if outcome.status == 'READY_FOR_REVIEW':
            queue.finish(lease, 'PREPARED', evidence=evidence)
        elif outcome.status in ('SKIPPED_DUPLICATE', 'SKIPPED_UNQUALIFIED'):
            queue.finish(lease, 'SKIPPED', 'already_applied_or_duplicate' if outcome.status == 'SKIPPED_DUPLICATE' else 'profile_match_below_threshold')
        elif outcome.status == 'SKIPPED_INELIGIBLE':
            queue.finish(lease, 'NEEDS_INPUT' if 'unverified' in outcome.reason else 'SKIPPED',
                         'job_eligibility_requires_review' if 'unverified' in outcome.reason else 'job_ineligible')
        else:
            queue.finish(lease, 'NEEDS_INPUT', 'preparation_evidence_incomplete' if outcome.reason == 'preparation_evidence_incomplete' else 'job_requires_review')
        for name in totals: totals[name] += getattr(result, name)
        outcomes.extend(result.outcomes)
    return ReviewRunSummary(**totals, outcomes=tuple(outcomes)), stop
