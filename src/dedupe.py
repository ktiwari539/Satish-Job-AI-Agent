import re
from hashlib import sha256

from extractor import normalize_text
from models import Job


COMPANY_SUFFIXES = (
    " private limited",
    " pvt ltd",
    " pvt. ltd.",
    " limited",
    " ltd",
    " llc",
    " inc",
    " corporation",
    " corp",
)


def _clean_company(value: str) -> str:
    text = normalize_text(value)
    for suffix in COMPANY_SUFFIXES:
        normalized_suffix = normalize_text(suffix)
        if text.endswith(normalized_suffix):
            text = text[: -len(normalized_suffix)].strip()
    return text


def _clean_title(value: str) -> str:
    text = normalize_text(value)
    text = re.sub(r"\b(remote|hybrid|onsite|on-site)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_job_fingerprint(job: Job) -> str:
    company = _clean_company(job.company)
    title = _clean_title(job.title)
    location = normalize_text(job.location)
    payload = f"{company}|{title}|{location}"
    return sha256(payload.encode("utf-8")).hexdigest()
