"""Strict, single-listing LinkedIn inspection; never submit from this module.

A shared LinkedIn search URL identifies the selected job by currentJobId.
Only that one job is processed. No fallback to arbitrary search results.
"""
import re
import json
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from extractor import extract_minimum_years, extract_skills, detect_remote, html_to_text
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



def _safe_page_state(page) -> dict:
    """Report only structural signals, never user text, cookies or page HTML."""
    code = r"""() => {
      const body = document.body;
      const text = (body && body.innerText || '').toLowerCase();
      const has = (term) => text.includes(term);
      const blocked = has('verify your identity') || has('security checkpoint')
        || has('captcha') || has('verify you are human');
      const expired = has('job is no longer available')
        || has('no longer accepting applications') || has('job has expired');
      const signIn = !!document.querySelector('input[type="password"]')
        || !!document.querySelector('form[action*="login"]');
      const details = document.querySelectorAll(
        '.jobs-description, .jobs-description__content, .top-card-layout__title, ' +
        '.job-details-jobs-unified-top-card__job-title, .show-more-less-html__markup'
      ).length;
      return {
        body_chars: Math.min(text.length, 100000),
        main_count: Math.min(document.querySelectorAll('main').length, 100),
        detail_nodes: Math.min(details, 100),
        heading_count: Math.min(document.querySelectorAll('h1').length, 100),
        job_posting_scripts: Math.min(document.querySelectorAll('script[type="application/ld+json"]').length, 100),
        login_form_present: signIn,
        challenge_present: blocked,
        expired_text_present: expired,
      };
    }"""
    try:
        raw = page.evaluate(code)
        if not isinstance(raw, dict):
            return {"page_state": "probe_unavailable"}
        result = {
            key: raw.get(key) for key in (
                "body_chars", "main_count", "detail_nodes", "heading_count",
                "job_posting_scripts", "login_form_present",
                "challenge_present", "expired_text_present",
            )
        }
        if result.get("challenge_present"):
            state = "security_checkpoint"
        elif result.get("login_form_present"):
            state = "sign_in_interstitial"
        elif result.get("expired_text_present"):
            state = "listing_unavailable"
        elif result.get("body_chars", 0) < 40:
            state = "empty_or_unrendered_page"
        elif not result.get("detail_nodes"):
            state = "no_job_details_in_dom"
        else:
            state = "job_markup_unrecognized"
        result["page_state"] = state
        return result
    except Exception:
        return {"page_state": "probe_unavailable"}


def _structured_jobs(page):
    """Inspect bounded LinkedIn JSON-LD candidates without exporting content."""
    try:
        scripts = page.locator('script[type="application/ld+json"]')
        count = min(scripts.count(), 15)
    except Exception:
        return
    for index in range(count):
        try:
            value = scripts.nth(index).text_content(timeout=1200)
            if not value or len(value) > 200000:
                continue
            tree = json.loads(value)
            pending = [tree]
            inspected = 0
            while pending and inspected < 40:
                node = pending.pop()
                inspected += 1
                if isinstance(node, list):
                    pending.extend(node[:40])
                elif isinstance(node, dict):
                    kind = node.get("@type", "")
                    types = (kind,) if isinstance(kind, str) else kind
                    if isinstance(types, (list, tuple)) and "JobPosting" in types:
                        yield node
                    if "@graph" in node:
                        pending.append(node["@graph"])
        except (ValueError, TypeError, AttributeError, KeyError):
            continue
        except Exception:
            continue


def _structured_details(page, target: LinkedInTarget):
    """Require an explicit matching job identifier inside JSON-LD.

    The browser URL by itself is not sufficient evidence that LinkedIn
    actually rendered this job's information.
    """
    for node in _structured_jobs(page):
        reference = str(node.get("url") or "")
        ident = node.get("identifier") or {}
        ident_value = str(ident.get("value", "")) if isinstance(ident, dict) else str(ident)
        parsed = urlsplit(reference)
        match = re.fullmatch(r"/jobs/view/(?:[^/?]+-)?([0-9]{7,15})/?", parsed.path)
        url_matches = (
            (parsed.hostname or "").lower() in ("www.linkedin.com", "linkedin.com")
            and match is not None and match.group(1) == target.job_id
        )
        matched = (
            (bool(reference) or bool(ident_value))
            and (not reference or url_matches)
            and (not ident_value or ident_value == target.job_id)
        )
        if not matched:
            continue
        title = " ".join(str(node.get("title") or "").split())
        hiring = node.get("hiringOrganization") or {}
        company = " ".join(str(hiring.get("name") or "").split()) if isinstance(hiring, dict) else ""
        location_item = node.get("jobLocation") or {}
        if isinstance(location_item, list):
            location_item = location_item[0] if location_item else {}
        address = location_item.get("address") or {} if isinstance(location_item, dict) else {}
        if not isinstance(address, dict):
            address = {}
        location = ", ".join(
            str(address.get(key) or "").strip()
            for key in ("addressLocality", "addressRegion", "addressCountry")
            if str(address.get(key) or "").strip()
        )
        description = " ".join(html_to_text(str(node.get("description") or "")).split())
        if title and company and location and len(description) >= 120:
            return title, company, location, description
    return None


def inspect_exact_linkedin_job(page, target: LinkedInTarget, taxonomy: tuple) -> Job:
    """Read exactly one authenticated job detail page, or fail closed."""
    bounded_goto(page, target.url)
    ensure_exact_target(page, target)

    def inspect_fields():
        return (
            _first_visible_text(page, TITLE_SELECTORS),
            _first_visible_text(page, COMPANY_SELECTORS),
            _first_visible_text(page, LOCATION_SELECTORS),
            _first_visible_text(page, DESCRIPTION_SELECTORS),
        )

    title, company, location, description = inspect_fields()
    if not title or not company or not location or len(description) < 120:
        # Navigation commit and DOM-ready do not guarantee that LinkedIn's
        # asynchronously rendered job detail metadata has appeared.
        try:
            page.wait_for_timeout(1100)
        except Exception:
            pass
        ensure_exact_target(page, target)
        title, company, location, description = inspect_fields()

    if not title or not company or not location or len(description) < 120:
        structured = _structured_details(page, target)
        if structured is not None:
            title, company, location, description = structured
            trace_event("exact_job_structured_data_used", job_id=target.job_id)

    missing = [
        field for field, value in (
            ("title", title), ("company", company), ("location", location)
        ) if not value
    ]
    page_probe = _safe_page_state(page) if missing or len(description) < 120 else {}
    trace_event(
        "exact_job_metadata_probe",
        job_id=target.job_id,
        title_present=bool(title),
        company_present=bool(company),
        location_present=bool(location),
        description_length=len(description),
        missing_fields=missing,
        page_probe=page_probe,
    )

    # Never infer the identity or company from unrelated search-card text.
    if missing:
        state = page_probe.get("page_state", "unknown_page_state")
        raise ValueError("exact_job_metadata_unverified:" + ",".join(missing) + ":" + state)
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
