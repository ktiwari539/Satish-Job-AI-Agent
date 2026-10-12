"""Read-only import of job data explicitly exported from signed-in regular Chrome.

No browser automation, session cookies, credentials, job application, or email.
The export file stays local; only an explicit user action transfers job-only data.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from automation_policy import load_automation_policy
from browser_extractors import RawJobCard, normalize_browser_cards
from matcher import score_profile
from models import CandidateProfile
from policy import evaluate_eligibility
from store import JobStore

MAX_EXPORT_BYTES = 2_000_000
MIN_FULL_JD_CHARS = 200


def valid_naukri_url(raw: str) -> bool:
    if not isinstance(raw, str):
        return False
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https"
            and (host == "naukri.com" or host.endswith(".naukri.com"))
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and bool(parsed.path.strip("/"))
        )
    except (ValueError, AttributeError):
        return False


def parse_export(payload: dict, taxonomy: tuple[str, ...]) -> list[tuple[object, bool]]:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1 or payload.get("portal") != "naukri":
        raise ValueError("unsupported_naukri_export")
    data = payload.get("jobs")
    if not isinstance(data, list) or len(data) > 75:
        raise ValueError("invalid_job_list")
    page_kind = payload.get("page_kind")
    if page_kind not in ("search", "detail"):
        raise ValueError("unsupported_page_kind")

    output = []
    seen = set()
    for row in data:
        if not isinstance(row, dict):
            raise ValueError("invalid_job_record")
        title = row.get("title", "")
        company = row.get("company", "")
        location = row.get("location", "")
        url = row.get("url", "")
        description = row.get("description", "")
        kind = row.get("capture_kind", "")
        if not all(isinstance(v, str) for v in (title, company, location, url, description, kind)):
            raise ValueError("invalid_job_fields")
        if not valid_naukri_url(url):
            raise ValueError("unsafe_job_url")
        if not title.strip() or len(title) > 300 or len(company) > 300 or len(location) > 300 or len(description) > 25000:
            raise ValueError("invalid_job_fields")
        if kind not in ("search", "detail") or kind != page_kind:
            raise ValueError("inconsistent_job_capture_kind")
        card = RawJobCard(
            title=title, company=company, location=location,
            url=url, description=description if kind == "detail" else "",
        )
        normalized = normalize_browser_cards("naukri", [card], taxonomy)
        if not normalized:
            continue
        job = normalized[0]
        if job.url in seen:
            continue
        seen.add(job.url)
        # Search snippets are never trusted as full job descriptions.
        complete_description = kind == "detail" and len(description.strip()) >= MIN_FULL_JD_CHARS
        output.append((job, complete_description))
    return output


def evaluate_export(payload: dict, profile, policy, store) -> dict:
    jobs = parse_export(payload, profile.skill_taxonomy)
    decisions = []
    counts = dict(discovered=len(jobs), full_jd=0, qualified=0, needing_full_jd=0, blocked=0)
    for job, is_full_jd in jobs:
        decision = dict(title=job.title, company=job.company, url=job.url, status="NEEDS_FULL_JD", score=None)
        if not is_full_jd or not job.company:
            counts["needing_full_jd"] += 1
        else:
            counts["full_jd"] += 1
            if store.is_recent_similar_application(job, cooldown_days=policy.duplicate_cooldown_days):
                decision["status"] = "SKIPPED_RECENT_APPLICATION"
            else:
                score = score_profile(profile, job, threshold=policy.threshold)
                eligibility = evaluate_eligibility(profile, job)
                decision["score"] = score.score
                if score.decision != "APPLY":
                    decision["status"] = "BELOW_MATCH_THRESHOLD"
                elif not eligibility.eligible:
                    decision["status"] = "INELIGIBLE"
                else:
                    decision["status"] = "QUALIFIED_FOR_REVIEW"
                    counts["qualified"] += 1
        decisions.append(decision)
    return {
        "portal": "naukri", "mode": "READ_ONLY",
        "submitted": 0, "confirmed": 0, "threshold": policy.threshold,
        **counts, "jobs": decisions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score user-exported Naukri jobs without browser login")
    parser.add_argument("--file", required=True, help="Local JSON export downloaded by Chrome extension")
    parser.add_argument("--profile", default="config/qa_profile.json")
    parser.add_argument("--policy", default="config/automation_policy.production.json")
    parser.add_argument("--db", default="data/jobs.db")
    parser.add_argument("--report", default="data/naukri_import_report.json")
    args = parser.parse_args()
    try:
        data_path = Path(args.file).expanduser()
        if data_path.stat().st_size > MAX_EXPORT_BYTES:
            raise ValueError("export_too_large")
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        profile = CandidateProfile.from_dict(json.loads(Path(args.profile).read_text(encoding="utf-8")))
        policy = load_automation_policy(args.policy)
        result = evaluate_export(payload, profile, policy, JobStore(args.db))
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "status": "imported", "discovered": result["discovered"],
            "full_jd": result["full_jd"], "qualified": result["qualified"],
            "needing_full_jd": result["needing_full_jd"],
            "submitted": 0, "confirmed": 0, "report": str(target),
        }, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "import_rejected", "reason": str(exc)[:160]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
