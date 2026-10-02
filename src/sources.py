import json
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from extractor import detect_remote, extract_minimum_years, extract_skills, html_to_text
from models import Job


USER_AGENT = "JobAIAgent-ZeroCost-DryRun/0.2"


def _get_json(url: str, timeout: int = 15) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_greenhouse(payload: dict, board_token: str, taxonomy: tuple[str, ...]) -> list[Job]:
    jobs: list[Job] = []
    for item in payload.get("jobs", []):
        description = html_to_text(item.get("content", ""))
        location = (item.get("location") or {}).get("name", "")
        title = item.get("title", "")
        jobs.append(
            Job(
                source="greenhouse",
                external_id=str(item.get("id", "")),
                company=board_token,
                title=title,
                location=location,
                url=item.get("absolute_url", ""),
                description=description,
                required_skills=extract_skills(description, taxonomy),
                minimum_years=extract_minimum_years(description),
                remote=detect_remote(title, location, description),
            )
        )
    return jobs


def discover_greenhouse(board_token: str, taxonomy: tuple[str, ...]) -> list[Job]:
    token = quote(board_token.strip(), safe="")
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    return parse_greenhouse(_get_json(url), board_token, taxonomy)


def _lever_description(item: dict) -> str:
    parts = [item.get("descriptionPlain", ""), item.get("additionalPlain", "")]
    if not any(parts):
        parts = [item.get("description", ""), item.get("additional", "")]
    return html_to_text(" ".join(p for p in parts if p))


def parse_lever(payload: list[dict], site: str, taxonomy: tuple[str, ...]) -> list[Job]:
    jobs: list[Job] = []
    for item in payload:
        categories = item.get("categories") or {}
        description = _lever_description(item)
        location = categories.get("location", "")
        title = item.get("text", "")
        jobs.append(
            Job(
                source="lever",
                external_id=str(item.get("id", "")),
                company=site,
                title=title,
                location=location,
                url=item.get("hostedUrl") or item.get("applyUrl") or "",
                description=description,
                required_skills=extract_skills(description, taxonomy),
                minimum_years=extract_minimum_years(description),
                remote=detect_remote(title, location, description),
            )
        )
    return jobs


def discover_lever(site: str, taxonomy: tuple[str, ...]) -> list[Job]:
    slug = quote(site.strip(), safe="")
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    payload = _get_json(url)
    if not isinstance(payload, list):
        raise ValueError("Lever response was not a job list")
    return parse_lever(payload, site, taxonomy)
