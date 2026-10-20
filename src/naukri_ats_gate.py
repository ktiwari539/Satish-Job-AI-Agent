"""Fail-closed verification of a user-observed external ATS form.

An inspection is NOT proof of external navigation, form completion, or submission.
No network calls, browser commands, application database writes, or credentials.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from naukri_browser_import import valid_naukri_url
from naukri_review_queue import qualified_jobs


def audit_ats_form(report: dict, inspection: dict) -> dict:
    if not isinstance(inspection, dict):
        raise ValueError("invalid_ats_inspection")
    if inspection.get("schema_version") != 1 or inspection.get("portal") != "external_ats":
        raise ValueError("unexpected_ats_inspection_schema")
    if inspection.get("mode") != "READ_ONLY_FORM_INSPECTION":
        raise ValueError("ats_inspection_must_be_read_only")
    if inspection.get("status") != "read_only_inspection":
        raise ValueError("unsupported_ats_page")
    if inspection.get("submitted") != 0 or inspection.get("confirmed") != 0:
        raise ValueError("no_submission_evidence_is_supported")
    if inspection.get("handoff_method") != "user_reported_external_apply":
        raise ValueError("unsupported_handoff_method")
    if inspection.get("handoff_navigation_verified") is not False:
        raise ValueError("navigation_provenance_is_not_verified")

    origin = inspection.get("site_origin")
    if not isinstance(origin, str) or len(origin) > 220:
        raise ValueError("invalid_ats_origin")
    try:
        url = urlsplit(origin)
        host = (url.hostname or "").casefold()
        if (
            url.scheme != "https" or not host or url.path or
            url.query or url.fragment or url.username or url.password or
            url.port not in (None, 443) or
            host == "naukri.com" or host.endswith(".naukri.com") or
            host == "google.com" or host.endswith(".google.com") or
            host == "gmail.com" or host.endswith(".gmail.com")
        ):
            raise ValueError("invalid_ats_origin")
    except ValueError as exc:
        raise ValueError("invalid_ats_origin") from exc

    job_url = inspection.get("source_naukri_job_url")
    if not valid_naukri_url(job_url):
        raise ValueError("invalid_source_naukri_job_url")
    eligible = next((j for j in qualified_jobs(report) if j["url"] == job_url), None)
    if eligible is None:
        return {
            "status": "ATS_NOT_FOR_QUALIFIED_JOB",
            "source_job_url": job_url,
            "ats_origin": origin,
            "qualified_job_matched": False,
            "submitted": 0, "confirmed": 0,
        }

    fields = inspection.get("fields")
    actions = inspection.get("action_controls")
    if not isinstance(fields, list) or len(fields) > 50 or not all(isinstance(f, dict) for f in fields):
        raise ValueError("invalid_form_field_summary")
    if not isinstance(actions, list) or not all(isinstance(a, str) for a in actions):
        raise ValueError("invalid_form_action_summary")
    auth = any(inspection.get(flag) is True for flag in (
        "captcha_present", "otp_present", "login_required"
    ))
    return {
        "status": "HUMAN_SECURITY_ACTION_REQUIRED" if auth else "ATS_FORM_OBSERVED_UNVERIFIED_HANDOFF",
        "source_job_url": job_url,
        "ats_origin": origin,
        "qualified_job_matched": True,
        "read_only": True,
        "handoff_navigation_verified": False,
        "field_count": len(fields),
        "required_field_count": sum(f.get("required") is True for f in fields),
        "unclassified_question_count": sum(f.get("category") == "other_question" for f in fields),
        "submit_control_detected": "submit_application" in actions,
        "submitted": 0, "confirmed": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit exact-job ATS inspection without authorizing or submitting an application"
    )
    parser.add_argument("--inspection", required=True)
    parser.add_argument("--report", default="data/naukri_import_report.json")
    args = parser.parse_args()
    try:
        for arg in (args.inspection, args.report):
            source = Path(arg).expanduser()
            if not source.is_file() or source.stat().st_size > 1_000_000:
                raise ValueError("missing_or_oversized_inspection_or_report")
        inspection = json.loads(Path(args.inspection).expanduser().read_text(encoding="utf-8"))
        report = json.loads(Path(args.report).expanduser().read_text(encoding="utf-8"))
        result = audit_ats_form(report, inspection)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["qualified_job_matched"] else 4
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "ATS_AUDIT_BLOCKED", "reason": str(exc)[:160]}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
