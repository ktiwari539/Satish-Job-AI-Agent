"""Read-only fallback for one selected LinkedIn search-result job.

The target card must be identified independently by exact job ID before any
click. Clicking a search result is navigation, never a job application.
"""
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from agent_trace import trace_event
from extractor import detect_remote, extract_minimum_years, extract_skills
from models import Job
from navigation import bounded_goto
from linkedin_exact_job import LinkedInTarget, _first_visible_text


DETAIL_ROOTS = (
    ".jobs-search__job-details--container",
    ".jobs-search__job-details",
    ".jobs-details",
    ".jobs-details__main-content",
    ".scaffold-layout__detail",
)
DETAIL_TITLE = (
    ".job-details-jobs-unified-top-card__job-title",
    ".jobs-unified-top-card__job-title",
    ".jobs-details-top-card__job-title",
    "h1",
)
DETAIL_COMPANY = (
    ".job-details-jobs-unified-top-card__company-name",
    ".jobs-unified-top-card__company-name",
    ".jobs-details-top-card__company-url",
)
DETAIL_LOCATION = (
    ".job-details-jobs-unified-top-card__primary-description-container",
    ".jobs-unified-top-card__bullet",
    ".jobs-details-top-card__bullet",
)
DETAIL_DESCRIPTION = (
    ".jobs-description__content",
    ".jobs-box__html-content",
    ".jobs-description",
)
CARD_SELECTOR = "li.scaffold-layout__list-item, li.jobs-search-results__list-item, div.job-card-container"


def _job_id_from_card(card):
    for attr in ("data-job-id", "data-occludable-job-id"):
        try:
            val = str(card.get_attribute(attr) or "")
            if re.fullmatch(r"[0-9]{7,15}", val):
                return val
        except Exception:
            pass
    try:
        links = card.locator('a[href*="/jobs/view/"]')
        for i in range(min(links.count(), 4)):
            href = links.nth(i).get_attribute("href") or ""
            match = re.search(r"/jobs/view/(?:[^/?]+-)?([0-9]{7,15})(?:[/?]|$)", href)
            if match:
                return match.group(1)
    except Exception:
        pass
    return ""


def _selected_route_verified(page, target):
    parsed = urlsplit(str(getattr(page, "url", "") or ""))
    vals = parse_qs(parsed.query).get("currentJobId", [])
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() in ("www.linkedin.com", "linkedin.com")
        and parsed.path.rstrip("/") in ("/jobs/search", "/jobs/search-results")
        and vals == [target.job_id]
    )


def _job_fields_within_details(page):
    for selector in DETAIL_ROOTS:
        try:
            matches = page.locator(selector)
            for i in range(min(matches.count(), 4)):
                scope = matches.nth(i)
                if not scope.is_visible():
                    continue
                title = _first_visible_text(scope, DETAIL_TITLE)
                company = _first_visible_text(scope, DETAIL_COMPANY)
                location = _first_visible_text(scope, DETAIL_LOCATION)
                description = _first_visible_text(scope, DETAIL_DESCRIPTION)
                if title and company and location and len(description) >= 120:
                    return title, company, location, description
        except Exception:
            continue
    return None


def inspect_selected_search_job(page, target: LinkedInTarget, taxonomy: tuple,
                                keywords: str = "Customer Success Manager") -> Job:
    """Strict single-result DOM inspection, never scroll/apply/select another job."""
    if not keywords or len(keywords) > 150:
        raise ValueError("exact_search_keywords_invalid")
    url = "https://www.linkedin.com/jobs/search-results/?" + urlencode({
        "currentJobId": target.job_id,
        "keywords": keywords,
    })
    bounded_goto(page, url)
    if not _selected_route_verified(page, target):
        raise ValueError("exact_search_route_id_unverified")
    try:
        cards = page.locator(CARD_SELECTOR)
        count = min(cards.count(), 150)
    except Exception:
        count = 0
    matched = []
    for i in range(count):
        card = cards.nth(i)
        if _job_id_from_card(card) == target.job_id:
            matched.append(card)
    trace_event("exact_search_card_probe", job_id=target.job_id,
                inspected_card_count=count, matching_card_count=len(matched))
    if len(matched) != 1:
        raise ValueError("exact_search_target_card_not_unique_or_not_found")
    card = matched[0]
    if not card.is_visible():
        raise ValueError("exact_search_target_card_not_visible")
    # Clicking the verified result card selects a details panel. It cannot
    # submit an application; this module has no access to the Apply engine.
    card.click(timeout=3000)
    try:
        page.wait_for_timeout(900)
    except Exception:
        pass
    if not _selected_route_verified(page, target):
        raise ValueError("exact_search_selection_changed_job_id")
    details = _job_fields_within_details(page)
    trace_event("exact_search_detail_probe", job_id=target.job_id,
                verified_details_present=bool(details))
    if details is None:
        raise ValueError("exact_search_selected_detail_unverified")
    title, company, location, description = details
    return Job(
        source="linkedin", external_id=target.job_id, company=company,
        title=title, location=location, url=target.url,
        description=description,
        required_skills=extract_skills(description, taxonomy),
        minimum_years=extract_minimum_years(description),
        remote=detect_remote(title, location, description),
    )
