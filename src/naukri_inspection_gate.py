"""Correlate a Naukri application inspection with its EXACT qualified job.

Read-only gate. Never clicks Apply, submits, writes to the application store,
or mistakes a pre-Apply page for positive submission evidence.
"""
import argparse
import json
from pathlib import Path

from naukri_browser_import import valid_naukri_url
from naukri_review_queue import qualified_jobs


def correlate_inspection(report: dict, inspection: dict) -> dict:
    if not isinstance(inspection, dict) or inspection.get("portal") != "naukri":
        raise ValueError("not_naukri_application_inspection")
    if inspection.get("schema_version") not in (1, 2):
        raise ValueError("unsupported_inspection_schema")
    if inspection.get("mode") != "READ_ONLY_INSPECTION":
        raise ValueError("inspection_must_be_read_only")
    url = inspection.get("job_url")
    if not valid_naukri_url(url):
        raise ValueError("invalid_inspection_job_url")
    jobs = qualified_jobs(report)
    job = next((item for item in jobs if item["url"] == url), None)
    base = dict(
        portal="naukri", inspection_job_url=url,
        qualified_job_matched=job is not None,
        submitted=0, confirmed=0,
    )
    if not job:
        return {**base, "status": "INSPECTION_NOT_FOR_QUALIFIED_JOB",
                "reason": "Match the inspection URL with an exact qualified URL in this report."}
    if any(inspection.get(key) is True for key in (
        "captcha_present", "otp_present", "account_login_present",
    )):
        return {**base, "status": "HUMAN_AUTHENTICATION_REQUIRED",
                "reason": "Do not automate or bypass security challenges."}
    categories = inspection.get("application_controls", [])
    if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
        raise ValueError("invalid_application_controls")
    if "already_applied" in categories:
        return {**base, "status": "POSSIBLY_ALREADY_APPLIED",
                "reason": "Verify against the portal and application database before any retry."}
    if "external_apply" in categories:
        return {**base, "status": "EXTERNAL_APPLICATION_INSPECTION_REQUIRED",
                "reason": "Inspect the employer ATS. This page is not submission confirmation."}
    if "apply" in categories:
        return {**base, "status": "NAUKRI_APPLY_CONTROL_REVIEW_REQUIRED",
                "reason": "Naukri Apply may be a one-click submission. No automatic click is authorized by this inspection."}
    return {**base, "status": "NO_VERIFIED_APPLICATION_CONTROL",
            "reason": "No actionable apply control was established."}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the exact inspected Naukri job before any application")
    parser.add_argument("--inspection", required=True)
    parser.add_argument("--report", default="data/naukri_import_report.json")
    args = parser.parse_args()
    try:
        for value in (args.inspection, args.report):
            path = Path(value).expanduser()
            if not path.is_file() or path.stat().st_size > 1_000_000:
                raise ValueError("missing_or_oversized_file")
        inspect = json.loads(Path(args.inspection).expanduser().read_text(encoding="utf-8"))
        report = json.loads(Path(args.report).expanduser().read_text(encoding="utf-8"))
        result = correlate_inspection(report, inspect)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["qualified_job_matched"] else 4
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "INSPECTION_GATE_BLOCKED", "reason": str(exc)[:160]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
