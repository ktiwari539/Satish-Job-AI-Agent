from dataclasses import dataclass, replace

from extractor import detect_remote, extract_minimum_years, extract_skills
from models import Job


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


def _read_first_visible(page, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        try:
            target = page.locator(selector).first
            if target.count():
                text = target.inner_text(timeout=3000).strip()
                if text:
                    return text
        except Exception:
            continue
    return ""


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
    page.goto(job.url, wait_until="domcontentloaded")
    return enrich_job_from_text(job, extract_full_jd(page, job.source), taxonomy)
