from dataclasses import dataclass, replace
import time

from extractor import detect_remote, extract_minimum_years, extract_skills
from models import Job
from navigation import bounded_goto


@dataclass(frozen=True)
class EnrichmentResult:
    job: Job
    enriched: bool
    reason: str = ""


JD_SELECTORS: dict[str, tuple[str, ...]] = {
    "linkedin": (
        ".jobs-description__content",
        ".jobs-box__html-content",
        ".jobs-description",
        ".show-more-less-html__markup",
        ".description__text",
        "#job-details",
        "[data-testid='job-description']",
    ),
    "naukri": (
        ".job-desc",
        ".styles_JDC__dang-inner-html__h0K4t",
        ".job-description",
    ),
    "indeed": (
        "#jobDescriptionText",
        ".jobsearch-JobComponent-description",
    ),
    "wellfound": (
        "[data-test='JobDescription']",
        ".styles_description__",
    ),
    "cutshort": (
        "[data-testid='job-description']",
        ".job-description",
    ),
    "foundit": (
        ".jobDescription",
        ".job-description",
    ),
    "hirist": (
        ".job-description",
        ".job-detail-description",
    ),
    "glassdoor": (
        "[data-test='jobDescriptionContent']",
        ".JobDetails_jobDescription__",
    ),
    "instahyre": (
        ".job-description",
        ".opportunity-description",
    ),
    "workday": (
        "[data-automation-id='jobPostingDescription']",
        "[data-automation-id='jobPostingPage']",
    ),
    "greenhouse": (
        "#content",
        ".job__description",
    ),
    "lever": (
        ".section-wrapper.page-full-width",
        ".posting-page",
    ),
}


def _read_first_visible(page, selectors: tuple[str, ...], *, min_chars=1, deadline=None) -> str:
    longest = ""
    for selector in selectors:
        if deadline is not None and time.monotonic() >= deadline:
            return longest
        try:
            matches = page.locator(selector)
            for index in range(min(matches.count(), 12)):
                remaining = deadline-time.monotonic() if deadline is not None else 3
                if remaining <= 0:
                    return longest
                target = matches.nth(index)
                if not target.is_visible():
                    continue
                text = target.inner_text(timeout=min(3000,max(1,int(remaining*1000)))).strip()
                if len(text) >= min_chars:
                    return text
                if len(text) > len(longest):
                    longest = text
        except Exception:
            continue
    return longest


def extract_full_jd(page, portal: str) -> str:
    selectors = JD_SELECTORS.get(portal.lower().strip(), ())
    text = _read_first_visible(page, selectors)
    if text:
        return text
    try:
        body = page.locator("body").inner_text(timeout=3000).strip()
    except Exception:
        return ""
    return body


def enrich_job_from_text(job: Job, full_description: str, taxonomy: tuple[str, ...]) -> EnrichmentResult:
    description = " ".join(full_description.split()).strip()
    if len(description) < 120:
        return EnrichmentResult(job=job, enriched=False, reason="jd_too_short_or_missing")

    enriched = replace(
        job,
        description=description,
        required_skills=extract_skills(description, taxonomy),
        minimum_years=extract_minimum_years(description),
        remote=detect_remote(job.title, job.location, description),
    )
    return EnrichmentResult(job=enriched, enriched=True)


def enrich_job_with_page(page, job: Job, taxonomy: tuple[str, ...]) -> EnrichmentResult:
    bounded_goto(page, job.url)
    return enrich_job_from_text(job, extract_full_jd(page, job.source), taxonomy)
