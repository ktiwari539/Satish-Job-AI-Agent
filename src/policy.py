from models import CandidateProfile, EligibilityResult, Job
from extractor import normalize_text
from international import detect_international_signals


INDIA_MARKERS = {
    "india", "mumbai", "bangalore", "bengaluru", "pune", "hyderabad",
    "delhi", "gurgaon", "gurugram", "noida", "chennai", "kolkata",
    "ahmedabad", "indore", "jaipur", "kochi", "cochin",
}


def _is_india_location(location: str) -> bool:
    text = normalize_text(location)
    return any(marker in text for marker in INDIA_MARKERS)


def evaluate_eligibility(profile: CandidateProfile, job: Job) -> EligibilityResult:
    reasons: list[str] = []
    india_location = _is_india_location(job.location)

    if india_location and not profile.india_authorized:
        reasons.append("not_authorized_for_india")

    signals = detect_international_signals(job)

    if not india_location and profile.outside_india_sponsorship_required:
        if signals.sponsorship_negative:
            reasons.append("outside_india_requires_sponsorship_but_job_does_not_offer_it")
        elif not signals.has_positive_overseas_signal:
            reasons.append("outside_india_requires_explicit_sponsorship_or_relocation_signal")

    if job.remote and not profile.remote_allowed:
        reasons.append("remote_not_allowed_by_profile")

    if (
        job.minimum_years is not None
        and job.minimum_years > profile.total_experience_years + 2
    ):
        reasons.append("experience_shortfall_over_2_years")

    return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))
