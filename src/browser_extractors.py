from dataclasses import dataclass
from hashlib import sha256
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

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
    # Remove tracking, but retain query parameters that identify a job.
    # Indeed's /viewjob?jk=ID otherwise collapses every job to /viewjob.
    query = parse_qs(parts.query, keep_blank_values=True)
    host = (parts.hostname or "").lower()
    if host == "indeed.com" or host.endswith(".indeed.com"):
        identity = query.get("jk") or query.get("vjk") or []
        conflicting = query.get("jk") and query.get("vjk") and query["jk"] != query["vjk"]
        if len(identity) == 1 and identity[0] and not conflicting:
            return urlunsplit((parts.scheme, parts.netloc, "/viewjob", urlencode({"jk": identity[0]}), ""))
        if identity:
            identities = [(key, val) for key in ("jk", "vjk") for val in query.get(key, [])]
            return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(identities), ""))
    identity_keys = ("currentJobId", "gh_jid", "jobId", "job_id", "requisitionId", "reqId")
    identities = [(key, query[key][0]) for key in identity_keys
                  if len(query.get(key, [])) == 1 and query[key][0]]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(identities), ""))


def stable_external_id(portal: str, card: RawJobCard) -> str:
    if card.external_id.strip():
        return card.external_id.strip()
    parsed = urlsplit(card.url)
    if portal == "linkedin" and parsed.hostname in ("linkedin.com", "www.linkedin.com"):
        match = re.fullmatch(r"/jobs/view/(?:[^/?]+-)?(\d{7,15})/?", parsed.path)
        if match:
            return match.group(1)
    if portal == "indeed" and (parsed.hostname == "indeed.com" or (parsed.hostname or "").endswith(".indeed.com")):
        query = parse_qs(parsed.query, keep_blank_values=True)
        ids = query.get("jk") or query.get("vjk") or []
        if len(ids) == 1:
            return ids[0]
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
