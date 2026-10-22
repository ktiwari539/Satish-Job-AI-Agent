"""Read-only, exact-ID job metadata fallback from public LinkedIn job pages.

The private authenticated browser sometimes renders Easy Apply but omits the
job-detail HTML. An explicitly supplied PUBLIC LinkedIn job URL containing
the same numeric ID can supply the missing JD for scoring. This module never
reads browser cookies or profile data and never applies for a job.
"""
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from extractor import extract_minimum_years, extract_skills, detect_remote, html_to_text
from models import Job


MAX_PUBLIC_HTML_BYTES = 2_000_000


def exact_public_job_url(value: str, expected_job_id: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("invalid_public_job_url")
    parsed = urlsplit(value)
    if (parsed.scheme != "https"
            or parsed.hostname not in ("in.linkedin.com", "www.linkedin.com", "linkedin.com")
            or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment):
        raise ValueError("untrusted_public_job_url")
    match = re.fullmatch(r"/jobs/view/(?:[a-z0-9]+(?:-[a-z0-9]+)*-)?([0-9]{7,15})/?", parsed.path)
    if not match or match.group(1) != str(expected_job_id):
        raise ValueError("public_job_id_mismatch")
    # Preserve the original URL but never forward its query parameters.
    return parsed._replace(query="", fragment="").geturl()


class _PublicPage(HTMLParser):
    _styles = {
        "title": {"top-card-layout__title", "topcard__title"},
        "company": {"topcard__org-name-link"},
        "location": {"topcard__flavor--bullet"},
        "description": {"show-more-less-html__markup", "description__text"},
    }

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.active = []
        self.fields = {key: [] for key in self._styles}
        self.scripts = []
        self.script_depth = 0
        self.script_chunks = []

    def handle_starttag(self, tag, attrs):
        # Void elements have no closing tag in ordinary HTML. Counting
        # them as nested elements would corrupt section boundaries.
        void = tag in {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        }
        if not void:
            self.depth += 1
        attributes = dict(attrs)
        klasses = set((attributes.get("class") or "").split())
        for key, selectors in self._styles.items():
            if klasses.intersection(selectors):
                self.active.append((key, self.depth, []))
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self.script_depth = self.depth
            self.script_chunks = []

    def handle_data(self, value):
        if self.script_depth:
            self.script_chunks.append(value)
        for key, depth, chunks in self.active:
            chunks.append(value)

    def handle_endtag(self, tag):
        if tag in {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        }:
            return
        if self.script_depth == self.depth and tag == "script":
            self.scripts.append("".join(self.script_chunks))
            self.script_depth = 0
        keep = []
        for key, depth, chunks in self.active:
            if depth == self.depth:
                result = " ".join(" ".join(chunks).split())
                if result:
                    self.fields[key].append(result)
            else:
                keep.append((key, depth, chunks))
        self.active = keep
        self.depth = max(0, self.depth - 1)


def _job_data_from_scripts(scripts, expected_job_id):
    for script in scripts[:20]:
        try:
            pending = [json.loads(script)]
        except (TypeError, ValueError):
            continue
        visited = 0
        while pending and visited < 60:
            item = pending.pop()
            visited += 1
            if isinstance(item, list):
                pending.extend(item[:40])
                continue
            if not isinstance(item, dict):
                continue
            pending.extend(item.get("@graph", [])[:40] if isinstance(item.get("@graph"), list)
                           else [item["@graph"]] if "@graph" in item else [])
            kind = item.get("@type", "")
            if "JobPosting" not in (kind if isinstance(kind, list) else [kind]):
                continue
            ref = str(item.get("url", "") or "")
            try:
                exact_public_job_url(ref, expected_job_id)
            except (ValueError, TypeError):
                continue
            hiring = item.get("hiringOrganization") or {}
            location = item.get("jobLocation") or {}
            if isinstance(location, list):
                location = location[0] if location else {}
            address = location.get("address") or {} if isinstance(location, dict) else {}
            if isinstance(address, str):
                address = {"addressCountry": address}
            if not isinstance(address, dict):
                address = {}
            return (
                str(item.get("title") or "").strip(),
                str(hiring.get("name") or "").strip() if isinstance(hiring, dict) else "",
                ", ".join(str(address.get(k, "") or "").strip()
                          for k in ("addressLocality", "addressRegion", "addressCountry")
                          if str(address.get(k, "") or "").strip()),
                " ".join(html_to_text(str(item.get("description") or "")).split()),
            )
    return None


def parse_public_job_html(html: str, expected_job_id: str, taxonomy: tuple) -> Job:
    parser = _PublicPage()
    parser.feed(html)
    from_scripts = _job_data_from_scripts(parser.scripts, expected_job_id)
    if from_scripts and all(from_scripts[:3]) and len(from_scripts[3]) >= 120:
        title, company, location, description = from_scripts
    else:
        title = next(iter(parser.fields["title"]), "")
        company = next(iter(parser.fields["company"]), "")
        location = next(iter(parser.fields["location"]), "")
        description = next(iter(parser.fields["description"]), "")
    if not title or not company or not location or len(description) < 120:
        raise ValueError("public_exact_job_metadata_incomplete")
    if re.search(
        r"this job is no longer available|no longer accepting applications|"
        r"this job has expired|position has been filled", description, re.I
    ):
        raise ValueError("public_exact_job_closed")
    return Job(
        source="linkedin", external_id=str(expected_job_id),
        company=company, title=title, location=location,
        url=f"https://www.linkedin.com/jobs/view/{expected_job_id}/",
        description=description,
        required_skills=extract_skills(description, taxonomy),
        minimum_years=extract_minimum_years(description),
        remote=detect_remote(title, location, description),
    )


def fetch_public_exact_linkedin_job(public_url: str, target, taxonomy: tuple) -> Job:
    validated = exact_public_job_url(public_url, target.job_id)
    request = Request(
        validated,
        headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
        method="GET",
    )
    # No browser profile, password, login token or cookie is used.
    try:
        with urlopen(request, timeout=12) as response:
            exact_public_job_url(response.geturl(), target.job_id)
            body = response.read(MAX_PUBLIC_HTML_BYTES + 1)
    except ValueError:
        raise
    except Exception as exc:
        # Surface only the exception type; never log public response bodies,
        # cookies or personalized transport messages.
        raise ValueError("public_exact_job_fetch_failed:" + type(exc).__name__) from exc
    if len(body) > MAX_PUBLIC_HTML_BYTES:
        raise ValueError("public_job_response_oversize")
    html = body.decode("utf-8", errors="replace")
    result = parse_public_job_html(html, target.job_id, taxonomy)
    if result.external_id != target.job_id or result.url != target.url:
        raise ValueError("public_job_identity_mismatch")
    return result
