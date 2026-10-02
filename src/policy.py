from models import CandidateProfile, EligibilityResult, Job
from extractor import normalize_text


INDIA_MARKERS = {
    "india", "mumbai", "bangalore", "bengaluru", "pune", "hyderabad",
    "delhi", "gurgaon", "gurugram", "noida", "chennai", "kolkata",
}


def _is_india_location(location: str) -> bool:
    text = normalize_text(location)
    return any(marker in text for marker in INDIA_MARKERS)


def evaluate_eligibility(profile: CandidateProfile, job: Job) -> EligibilityResult:
    text = normalize_text(f"{job.title} {job.location} {job.description}")
    reasons: list[str] = []

    if _is_india_location(job.location) and not profile.india_authorized:
        reasons.append("not_authorized_for_india")

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
    if sponsorship_block and not _is_india_location(job.location):
        if profile.outside_india_sponsorship_required:
            reasons.append("outside_india_requires_sponsorship_but_job_does_not_offer_it")

    if job.remote and not profile.remote_allowed:
        reasons.append("remote_not_allowed_by_profile")

    return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))
