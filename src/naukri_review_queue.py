"""Open one explicitly qualified Naukri job in the user's regular Chrome.

Consumes the existing read-only import report. Never uses browser cookies,
credentials, or Playwright, and never clicks Apply or Submit.
"""
import argparse
import json
import platform
import subprocess
from pathlib import Path

from naukri_browser_import import valid_naukri_url

MAX_REVIEW_JOBS = 75


def qualified_jobs(report: dict) -> list[dict]:
    if not isinstance(report, dict) or report.get("portal") != "naukri" or report.get("mode") != "READ_ONLY":
        raise ValueError("not_a_naukri_read_only_report")
    if report.get("submitted") != 0 or report.get("confirmed") != 0:
        raise ValueError("report_submission_state_unexpected")
    rows = report.get("jobs")
    if not isinstance(rows, list) or len(rows) > MAX_REVIEW_JOBS:
        raise ValueError("invalid_review_report")
    selected = []
    seen = set()
    threshold = report.get("threshold", 75)
    if not isinstance(threshold, int) or threshold < 75 or threshold > 100:
        raise ValueError("invalid_match_threshold")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid_review_record")
        if row.get("status") != "QUALIFIED_FOR_REVIEW":
            continue
        score = row.get("score")
        url = row.get("url")
        if not isinstance(score, int) or score < threshold or not valid_naukri_url(url):
            raise ValueError("invalid_qualified_job")
        # Do not trust a report that declares both QUALIFIED and blocked.
        if row.get("review_flags"):
            raise ValueError("qualified_job_has_unresolved_review_flags")
        if url in seen:
            continue
        seen.add(url)
        selected.append({
            "title": str(row.get("title", ""))[:300],
            "company": str(row.get("company", ""))[:300],
            "url": url,
            "score": score,
        })
    return sorted(selected, key=lambda job: (-job["score"], job["company"], job["title"]))


def open_in_regular_chrome(url: str) -> None:
    if not valid_naukri_url(url):
        raise ValueError("unsafe_job_url")
    if platform.system() != "Darwin":
        raise RuntimeError("auto_open_is_supported_on_macos_only")
    subprocess.run(["open", "-a", "Google Chrome", url], check=True, timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Choose qualified Naukri jobs for supervised application review"
    )
    parser.add_argument("--report", default="data/naukri_import_report.json")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--open-first", action="store_true", help="Open only the top-qualified job in normal Google Chrome")
    args = parser.parse_args()
    try:
        path = Path(args.report).expanduser()
        if not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("read_only_report_missing_or_too_large")
        report = json.loads(path.read_text(encoding="utf-8"))
        jobs = qualified_jobs(report)
        if not jobs:
            print(json.dumps({"status": "no_qualified_jobs", "qualified": 0}, sort_keys=True))
            return 0
        if args.limit < 1 or args.limit > MAX_REVIEW_JOBS:
            raise ValueError("limit_must_be_between_1_and_75")
        result = {
            "status": "ready_for_review",
            "qualified": len(jobs),
            "jobs": jobs[:args.limit],
            "submitted": 0,
            "confirmed": 0,
            "opened": False,
        }
        if args.open_first:
            open_in_regular_chrome(jobs[0]["url"])
            result["opened"] = True
            result["opened_url"] = jobs[0]["url"]
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "review_queue_blocked", "reason": str(exc)[:180]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
