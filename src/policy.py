from models import CandidateProfile, EligibilityResult, Job
from extractor import normalize_text
from international import detect_international_signals
from dedupe import canonical_company
import re


INDIA_MARKERS = {
    "india", "mumbai", "bangalore", "bengaluru", "pune", "hyderabad",
    "delhi", "gurgaon", "gurugram", "noida", "chennai", "kolkata",
    "ahmedabad", "indore", "jaipur", "kochi", "cochin",
}


def _is_india_location(location: str) -> bool:
    text = normalize_text(location)
    return any(re.search(r'\b'+re.escape(marker)+r'\b', text) for marker in INDIA_MARKERS)


def evaluate_eligibility(profile: CandidateProfile, job: Job) -> EligibilityResult:
    reasons: list[str] = []
    if canonical_company(job.company) and canonical_company(job.company) in {canonical_company(c) for c in profile.excluded_companies}:
        reasons.append('company_excluded_by_profile')
    india_location = _is_india_location(job.location)
    location = normalize_text(job.location).strip()
    location_unknown = location in ('', 'remote', 'hybrid', 'onsite', 'on-site', 'unknown', 'not specified')

    if india_location and not profile.india_authorized:
        reasons.append("not_authorized_for_india")

    signals = detect_international_signals(job)
    global_remote = job.remote and signals.global_remote_positive

    if location_unknown and not global_remote:
        reasons.append('job_work_location_unverified')
    elif global_remote and not profile.india_authorized:
        reasons.append('global_remote_requires_verified_india_work_authorization')
    elif not india_location and profile.outside_india_sponsorship_required:
        if signals.sponsorship_negative:
            reasons.append("outside_india_requires_sponsorship_but_job_does_not_offer_it")
        elif not (signals.sponsorship_positive or global_remote):
            # Moving expenses do not establish visa/work-permit sponsorship.
            reasons.append("outside_india_requires_explicit_sponsorship_or_global_remote_signal")

    if job.remote and not profile.remote_allowed:
        reasons.append("remote_not_allowed_by_profile")

    if (
        job.minimum_years is not None
        and job.minimum_years > profile.total_experience_years + 2
    ):
        reasons.append("experience_shortfall_over_2_years")

    return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))
