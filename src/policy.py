from models import CandidateProfile, EligibilityResult, Job
from extractor import normalize_text


INDIA_MARKERS = {
    "india", "mumbai", "bangalore", "bengaluru", "pune", "hyderabad",
    "delhi", "gurgaon", "gurugram", "noida", "chennai", "kolkata",
    "ahmedabad", "indore", "jaipur", "kochi", "cochin",
}


def _is_india_location(location: str) -> bool:
    text = normalize_text(location)
    return any(marker in text for marker in INDIA_MARKERS)


def evaluate_eligibility(profile: CandidateProfile, job: Job) -> EligibilityResult:
    text = normalize_text(f"{job.title} {job.location} {job.description}")
    reasons: list[str] = []

    india_location = _is_india_location(job.location)

    if india_location and not profile.india_authorized:
        reasons.append("not_authorized_for_india")

    if not india_location and not job.remote:
        reasons.append("outside_preferred_location")

    sponsorship_block = any(
        phrase in text
        for phrase in (
            "no visa sponsorship",
            "unable to sponsor",
            "cannot sponsor",
            "will not sponsor",
            "without sponsorship",
        )
    )
    if sponsorship_block and not india_location:
        if profile.outside_india_sponsorship_required:
            reasons.append("outside_india_requires_sponsorship_but_job_does_not_offer_it")

    if job.remote and not profile.remote_allowed:
        reasons.append("remote_not_allowed_by_profile")

    if (
        job.minimum_years is not None
        and job.minimum_years > profile.total_experience_years + 2
    ):
        reasons.append("experience_shortfall_over_2_years")

    return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))
