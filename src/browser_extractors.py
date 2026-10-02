from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit

from extractor import detect_remote, extract_minimum_years, extract_skills
from models import Job


@dataclass(frozen=True)
class RawJobCard:
    title: str
    company: str
    location: str
    url: str
    external_id: str = ""
    description: str = ""


def canonicalize_job_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    # Strip query/fragment tracking to improve cross-run dedupe.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def stable_external_id(portal: str, card: RawJobCard) -> str:
    if card.external_id.strip():
        return card.external_id.strip()
    source = "|".join(
        (
            portal.strip().lower(),
            card.company.strip().lower(),
            card.title.strip().lower(),
            canonicalize_job_url(card.url).lower(),
        )
    )
    return sha256(source.encode("utf-8")).hexdigest()[:20]


def normalize_browser_card(
    portal: str,
    card: RawJobCard,
    taxonomy: tuple[str, ...],
) -> Job:
    description = card.description.strip()
    title = card.title.strip()
    location = card.location.strip()
    return Job(
        source=portal.strip().lower(),
        external_id=stable_external_id(portal, card),
        company=card.company.strip(),
        title=title,
        location=location,
        url=canonicalize_job_url(card.url),
        description=description,
        required_skills=extract_skills(description, taxonomy),
        minimum_years=extract_minimum_years(description),
        remote=detect_remote(title, location, description),
    )


def normalize_browser_cards(
    portal: str,
    cards: list[RawJobCard],
    taxonomy: tuple[str, ...],
) -> list[Job]:
    jobs: list[Job] = []
    seen: set[str] = set()
    for card in cards:
        if not card.title.strip() or not card.url.strip():
            continue
        job = normalize_browser_card(portal, card, taxonomy)
        if job.key in seen:
            continue
        seen.add(job.key)
        jobs.append(job)
    return jobs
