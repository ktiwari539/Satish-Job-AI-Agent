"""Naukri-specific, conservative eligibility and data-quality gates.

These gates never infer protected characteristics, override applicant details,
or turn a keyword-match score into proof that an application is appropriate.
"""
import re
from urllib.parse import urlsplit


_GENERIC_COMPANY = (
    "leading client", "hiring for top mnc", "hiring for a top mnc",
    "fortune 500 companies", "multinational company",
    "call ", "contact hr ", "confidential company",
)
_RESTRICTED_TITLE = re.compile(
    r"\b(?:female|male|women|men)\s*(?:candidates?\s*)?only\b",
    flags=re.I,
)
_NAUKRI_EXPERIENCE = re.compile(r"-(\d{1,2})-to-(\d{1,2})-years-", flags=re.I)


def clean_company_name(raw: str) -> str:
    """Discard Naukri ratings/review lines, not actual employer names."""
    lines = [line.strip() for line in str(raw).splitlines() if line.strip()]
    if not lines:
        return ""
    if len(lines) > 1 and re.match(r"^[\d.]+\s*[\d,.Kk]*\s*Reviews?$", lines[1], re.I):
        return lines[0]
    return lines[0] if len(lines) > 1 and all(
        re.match(r"^[\d.\sKk,]+\s*Reviews?$", item, re.I) for item in lines[1:]
    ) else str(raw).strip()


def job_readiness_flags(title: str, company: str, url: str, description: str, experience_years: int):
    """Return hard manual-review gates plus non-blocking verification notes.

    The advertised upper experience range is a caution, not a definitive
    employment restriction. Never infer applicant gender from their profile.
    """
    blocks = []
    warnings = []
    name = clean_company_name(company).casefold().strip()
    if any(name.startswith(marker) for marker in _GENERIC_COMPANY):
        blocks.append("unverified_employer_identity")
    if _RESTRICTED_TITLE.search(title):
        blocks.append("restricted_eligibility_needs_human_review")
    if "click the apply now button to read the full job description" in description.casefold():
        blocks.append("full_description_not_available")
    try:
        slug = urlsplit(url).path
        ranges = _NAUKRI_EXPERIENCE.findall(slug)
        if ranges and experience_years > int(ranges[-1][1]) + 2:
            blocks.append("experience_range_review_required")
    except (ValueError, TypeError):
        pass
    if "aggregated from external source" in description.casefold():
        warnings.append("aggregated_posting_verify_availability")
    return tuple(blocks), tuple(warnings)
