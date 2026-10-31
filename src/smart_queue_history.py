"""Bounded retry history for non-submitting LinkedIn QA.

Stored locally beside the configured jobs database, never in Git. A blocked
job is cooled down to avoid repeated browser drafts. Exact applied jobs
remain protected by the application ledger, which takes precedence.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

_MAX_ENTRIES = 1000
_COOLDOWN_HOURS = 24
ENVIRONMENT_FAILURE_STATUSES = frozenset({
    "browser_runtime_unavailable", "smart_queue_browser_unavailable",
    "debug_private_profile_unavailable", "debug_ledger_unavailable",
    "debug_linkedin_session_required", "smart_queue_session_required",
})


def _path(db):
    return Path(db).expanduser().resolve().parent / "smart_queue_history.json"


def read_history(db):
    if not db:
        return {}
    try:
        raw = json.loads(_path(db).read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("jobs"), dict):
            return raw["jobs"]
    except (OSError, ValueError, TypeError):
        pass
    return {}


def skip_reason(history, job_id, now=None):
    item = history.get(str(job_id))
    if not isinstance(item, dict):
        return ""
    # Confirmed on-page/local Applied evidence never expires as a QA cooldown.
    if item.get("entry_classification") == "ALREADY_APPLIED":
        return "already_applied"
    # Older certification runs incorrectly recorded missing Playwright as a
    # job attempt. Recover automatically without deleting real dedupe history.
    if item.get("status") in ENVIRONMENT_FAILURE_STATUSES:
        return ""
    try:
        attempted = datetime.fromisoformat(item["checked_at"])
        if attempted.tzinfo is None:
            return ""
        age = (now or datetime.now(timezone.utc)) - attempted
        if timedelta(0) <= age < timedelta(hours=_COOLDOWN_HOURS):
            return "recently_checked"
    except (KeyError, TypeError, ValueError):
        pass
    return ""


def record_check(db, job_id, status, flow_state, *, entry_classification=""):
    if not db or not str(job_id).isdigit():
        return
    if status in ENVIRONMENT_FAILURE_STATUSES:
        return
    path = _path(db)
    jobs = read_history(db)
    jobs[str(job_id)] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": str(status)[:100],
        "flow_state": str(flow_state)[:100],
        "entry_classification": str(entry_classification)[:100],
    }
    if len(jobs) > _MAX_ENTRIES:
        terminal = {k: v for k, v in jobs.items() if isinstance(v, dict)
                    and v.get("entry_classification") == "ALREADY_APPLIED"}
        transient = {k: v for k, v in jobs.items() if isinstance(v, dict) and k not in terminal}
        jobs = {**dict(sorted(transient.items(), key=lambda p: p[1].get("checked_at", ""))[-_MAX_ENTRIES:]),
                **terminal}
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps({"version": 1, "jobs": jobs},
                                   sort_keys=True), encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
