"""Strict, single-listing LinkedIn inspection; never submit from this module.

A shared LinkedIn search URL identifies the selected job by currentJobId.
Only that one job is processed. No fallback to arbitrary search results.
"""
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from extractor import extract_minimum_years, extract_skills, detect_remote
from models import Job
from navigation import bounded_goto
from agent_trace import trace_event


@dataclass(frozen=True)
class LinkedInTarget:
    job_id: str
    url: str


def parse_linkedin_target(raw_url: str) -> LinkedInTarget:
    if not isinstance(raw_url, str) or not 0 < len(raw_url) <= 4000:
        raise ValueError("invalid_linkedin_job_url")
    parsed = urlsplit(raw_url.strip())
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() not in ("www.linkedin.com", "linkedin.com")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("untrusted_linkedin_job_url")
    route = parsed.path.rstrip("/")
    if re.fullmatch(r"/jobs/view/[0-9]{7,15}", route):
        job_id = route.split("/")[-1]
    elif route in ("/jobs/search-results", "/jobs/search"):
        query = parse_qs(parsed.query, keep_blank_values=True)
        selected = query.get("currentJobId", [])
        if len(selected) != 1 or not re.fullmatch(r"[0-9]{7,15}", selected[0]):
            raise ValueError("missing_or_ambiguous_selected_linkedin_job")
        job_id = selected[0]
    else:
        raise ValueError("unsupported_linkedin_job_route")
    return LinkedInTarget(job_id, "https://www.linkedin.com/jobs/view/" + job_id + "/")


def _first_visible_text(page, selectors: tuple) -> str:
    """Inspect visible matching elements, including non-first DOM copies."""
    for selector in selectors:
        try:
            matches = page.locator(selector)
            for index in range(min(matches.count(), 12)):
                candidate = matches.nth(index) if hasattr(matches, "nth") else matches.first
                if candidate.is_visible():
                    value = " ".join(candidate.inner_text(timeout=2500).split())
                    if value:
                        return value
        except Exception:
            continue
    return ""

TITLE_SELECTORS = (
    ".job-details-jobs-unified-top-card__job-title h1",
    ".job-details-jobs-unified-top-card__job-title",
    ".jobs-unified-top-card__job-title",
    ".jobs-details-top-card__job-title",
    "h1.top-card-layout__title",
    ".top-card-layout__title",
    ".topcard__title",
    "main h1",
)
COMPANY_SELECTORS = (
    ".job-details-jobs-unified-top-card__company-name a",
    ".job-details-jobs-unified-top-card__company-name",
    ".jobs-unified-top-card__company-name a",
    ".jobs-unified-top-card__company-name",
    ".jobs-details-top-card__company-url",
    ".topcard__org-name-link",
)
LOCATION_SELECTORS = (
    ".job-details-jobs-unified-top-card__primary-description-container",
    ".jobs-unified-top-card__bullet",
    ".jobs-details-top-card__bullet",
    ".topcard__flavor--bullet",
)
DESCRIPTION_SELECTORS = (
    ".jobs-description__content",
    ".jobs-box__html-content",
    ".jobs-description",
    ".show-more-less-html__markup",
    ".description__text",
)


def ensure_exact_target(page, target: LinkedInTarget) -> None:
    """Never follow a login redirect, altered job ID or unrelated website."""
    current = str(getattr(page, "url", "") or "")
    parsed = urlsplit(current)
    if (parsed.hostname or "").lower() not in ("www.linkedin.com", "linkedin.com"):
        raise ValueError("exact_job_navigation_left_linkedin")
    match = re.fullmatch(r"/jobs/view/([0-9]{7,15})/?", parsed.path)
    if not match or match.group(1) != target.job_id:
        raise ValueError("exact_job_navigation_id_mismatch")


def inspect_exact_linkedin_job(page, target: LinkedInTarget, taxonomy: tuple) -> Job:
    """Read exactly one authenticated job detail page, or fail closed."""
    bounded_goto(page, target.url)
    ensure_exact_target(page, target)

    title = _first_visible_text(page, TITLE_SELECTORS)
    company = _first_visible_text(page, COMPANY_SELECTORS)
    location = _first_visible_text(page, LOCATION_SELECTORS)
    description = _first_visible_text(page, DESCRIPTION_SELECTORS)

    # Not enough evidence to score or submit, even if LinkedIn loaded a page.
    if not title or not company or not location:
        raise ValueError("exact_job_metadata_unverified")
    if len(description) < 120:
        raise ValueError("exact_job_description_missing_or_short")
    if re.search(
        r"(?:this job is no longer available|no longer accepting applications|"
        r"this job has expired|position has been filled)",
        description, re.I,
    ):
        raise ValueError("exact_job_closed")

    return Job(
        source="linkedin",
        external_id=target.job_id,
        company=company,
        title=title,
        location=location,
        url=target.url,
        description=description,
        required_skills=extract_skills(description, taxonomy),
        minimum_years=extract_minimum_years(description),
        remote=detect_remote(title, location, description),
    )
