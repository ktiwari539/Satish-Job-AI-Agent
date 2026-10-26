"""Bounded, non-submitting queue for LinkedIn Easy Apply QA.

This orchestrator never invokes a live submission adapter. It searches for
title-matching candidates, excludes a supplied previously blocked exact job,
and invokes the existing strict debug guard for each different candidate.
Results are structural only. Each candidate gets its own isolated browser
session so a stuck draft does not corrupt the next listing.
"""
import contextlib
import io
import json
import sys
from types import SimpleNamespace

from agent_trace import trace_event
from browser_portals import LinkedInBrowserAdapter
from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession
from linkedin_exact_job import parse_linkedin_target
from easy_apply_debug import debug_easy_apply, _first_matching_title
from smart_queue_history import read_history, skip_reason, record_check


def _get_debug_result(raw_output):
    """Extract a safe final status from structured debug output."""
    allowed = {
        "easy_apply_debug_review_reached",
        "easy_apply_debug_release_ready",
        "easy_apply_debug_review_unverified",
        "easy_apply_debug_blocked",
        "debug_already_applied_skipped",
        "debug_portal_already_applied_skipped",
        "debug_ambiguous_application_status_blocked",
        "debug_no_easy_apply_entry",
        "debug_linkedin_session_required",
        "debug_ledger_unavailable",
        "debug_private_profile_unavailable",
        "invalid_exact_job_target",
        "browser_runtime_unavailable",
    }
    result = None
    for line in raw_output.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("status") in allowed:
            result = item
    return result or {"status": "debug_no_structured_result"}


class _LocalTerminalTee:
    """Show applicant prompts while retaining safe summary output in memory."""

    def __init__(self, visible_stream, summary_buffer):
        self.visible_stream = visible_stream
        self.summary_buffer = summary_buffer

    def write(self, value):
        self.visible_stream.write(value)
        self.summary_buffer.write(value)

    def flush(self):
        self.visible_stream.flush()
        self.summary_buffer.flush()


def debug_easy_apply_queue(args):
    """Inspect up to five candidate forms, never Submit; no silent cross-job application."""
    if not (
        getattr(args, "debug_easy_apply_only", False)
        and getattr(args, "smart_debug", False)
    ):
        print(json.dumps({
            "status": "smart_queue_requires_non_submitting_smart_debug",
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2
    interactive = bool(getattr(args, "debug_interactive", False))
    if interactive and not sys.stdin.isatty():
        print(json.dumps({
            "status": "smart_queue_interactive_terminal_required",
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2
    if (getattr(args, "approve_one_live_application", False)
            or getattr(args, "allow_outside_window", False)):
        print(json.dumps({
            "status": "smart_queue_live_flags_forbidden",
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2

    ignored_job_id = ""
    try:
        if getattr(args, "job_url", ""):
            ignored_job_id = parse_linkedin_target(args.job_url).job_id
    except ValueError:
        print(json.dumps({
            "status": "invalid_exact_job_target",
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2

    # Bound form interactions, not just search candidates. This avoids
    # repeated drafts, throttling and unbounded browser sessions.
    candidate_limit = max(1, min(int(getattr(args, "max_jobs", 10)), 20))
    form_limit = max(1, min(int(getattr(args, "smart_max_forms", 3)), 5))
    jobs = []
    try:
        config = BrowserRuntimeConfig(
            user_data_dir=args.profile_dir,
            headless=args.headless, slow_mo_ms=125,
        )
        with PlaywrightSession(config) as runtime:
            adapter = LinkedInBrowserAdapter(runtime.page)
            login = adapter.login_state()
            if not login.authenticated or login.needs_human_action:
                print(json.dumps({
                    "status": "smart_queue_session_required",
                    "reason_code": "linkedin_authentication_required",
                    "attempted": 0, "confirmed": 0,
                }, sort_keys=True))
                return 4
            adapter.open_search(args.query, args.location)
            jobs = adapter.extract_search_results(())[:candidate_limit]
    except BrowserRuntimeUnavailable:
        print(json.dumps({
            "status": "smart_queue_browser_unavailable",
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 4
    except Exception as exc:
        trace_event("smart_queue_discovery_failed", error_type=type(exc).__name__)
        print(json.dumps({
            "status": "smart_queue_discovery_failed",
            "reason_code": type(exc).__name__,
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 4

    history_db = getattr(args, "db", None)
    history = read_history(history_db)
    results = []
    forms_checked = 0
    seen_ids = set()
    skipped = {"original": 0, "duplicate": 0, "title": 0, "url": 0, "cooldown": 0}
    for candidate in jobs:
        if forms_checked >= form_limit:
            break
        if _first_matching_title((candidate,), args.query) is None:
            skipped["title"] += 1
            continue
        try:
            jid = parse_linkedin_target(candidate.url).job_id
        except ValueError:
            skipped["url"] += 1
            continue
        if jid == ignored_job_id:
            skipped["original"] += 1
            continue
        if jid in seen_ids:
            skipped["duplicate"] += 1
            continue
        seen_ids.add(jid)
        if skip_reason(history, jid):
            skipped["cooldown"] += 1
            trace_event("smart_queue_cooldown_skipped", job_id=jid)
            continue

        # Reuse all local-ledger, on-site Applied-status, and verified
        # Easy Apply checks. Do not enable smart fallback again recursively.
        per_job = SimpleNamespace(**vars(args))
        per_job.job_url = candidate.url
        per_job.smart_debug = False
        per_job.smart_debug_queue = False
        # Explicit --debug-interactive permits the applicant to teach a
        # missing fact in the SAME browser session. Without it this remains
        # an unattended, bounded, non-submitting diagnostic queue.
        per_job.debug_interactive = interactive
        per_job.debug_hold_seconds = 0
        buffer = io.StringIO()
        destination = _LocalTerminalTee(sys.stdout, buffer) if interactive else buffer
        try:
            with contextlib.redirect_stdout(destination):
                exit_code = debug_easy_apply(per_job)
            item = _get_debug_result(buffer.getvalue())
        except Exception as exc:
            exit_code = 4
            item = {
                "status": "smart_queue_candidate_exception",
                "reason_code": type(exc).__name__,
            }

        status = str(item.get("status", "debug_no_structured_result"))
        state = str(item.get("flow_state", "NOT_RUN"))
        accepted = status in ("easy_apply_debug_review_reached",
                              "easy_apply_debug_release_ready",
                              "easy_apply_debug_review_unverified")
        form_tested = bool(item.get("flow_tested", status in (
            "easy_apply_debug_blocked",
            "easy_apply_debug_review_reached",
            "easy_apply_debug_release_ready",
            "easy_apply_debug_review_unverified",
        )))
        forms_checked += int(form_tested)
        result = {
            "job_id": jid,
            "status": status,
            "flow_state": state,
            "flow_tested": form_tested,
            "review_reached": accepted,
            "release_checks_passed": item.get("release_checks_passed") is True,
            "resume_evidence_state": str(
                item.get("resume_evidence_state", "not_checked")
            ) if form_tested else "not_checked",
            "review_mismatch_count": int(item.get("review_mismatch_count", 0))
            if type(item.get("review_mismatch_count", 0)) is int else 0,
            "unresolved_required_count": max(
                0, min(50, item.get("unresolved_required_count", 0))
            ) if type(item.get("unresolved_required_count", 0)) is int else 0,
            "exit_code": int(exit_code),
            "submission_enabled": False,
            "attempted": 0,
            "confirmed": 0,
        }
        results.append(result)
        if history_db:
            try:
                record_check(history_db, jid, status, state)
                history = read_history(history_db)
            except OSError as exc:
                trace_event("smart_queue_history_write_failed", error_type=type(exc).__name__)
        trace_event("smart_queue_job_result", **result)
        print(json.dumps({
            "event": "smart_queue_job_checked", **result
        }, sort_keys=True), flush=True)

    accepted = sum(bool(x["review_reached"]) for x in results)
    release_verified = sum(bool(x["release_checks_passed"]) for x in results)
    question_blocked = sum(
        bool(x["unresolved_required_count"]) for x in results
    )
    blocked = sum(
        bool(x["flow_tested"] and not x["review_reached"])
        for x in results
    )
    final = {
        "status": (
            "smart_queue_release_verified"
            if release_verified and release_verified == len(results) else
            "smart_queue_partial_release_verified"
            if release_verified else
            "smart_queue_review_unverified"
            if accepted else "smart_queue_no_review_verified"
        ),
        "searched": len(jobs),
        "checked": len(results),
        "forms_checked": forms_checked,
        "review_reached": accepted,
        "release_checks_passed": release_verified,
        "question_blocked_jobs": question_blocked,
        "blocked_forms": blocked,
        "form_limit": form_limit,
        "skipped": skipped,
        "ignored_original_job_id": ignored_job_id,
        "no_submit_clicks": True,
        "submission_enabled": False,
        "attempted": 0,
        "confirmed": 0,
        "next_action": (
            "review_safe_drafts_before_any_separate_submission_approval"
            if accepted else "inspect_per_job_blocker_reports"
        ),
    }
    trace_event("smart_queue_complete", **final)
    print(json.dumps(final, sort_keys=True))
    return 0 if release_verified else 4
