"""Non-submitting, one-job LinkedIn Easy Apply diagnostic.

This workflow deliberately does NOT import a submitter or run the live batch.
It may fill a draft application and click intermediate Next buttons, but never
Review/Submit or external-apply controls. Designed to diagnose the phone step
during the day without relaxing the real submission schedule.
"""
import json
import re
from pathlib import Path

from agent_trace import trace_event
from apply_inspection import inspect_linkedin_application_entry
from application_flow import run_safe_application_flow
from browser_portals import LinkedInBrowserAdapter
from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession
from live_blocker_capture import capture_blocker, hold_blocked_browser
from navigation import bounded_goto


def _safe_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("private_profile_must_be_object")
    return value


def _first_matching_title(jobs, query):
    tokens = [t for t in re.findall(r"[a-z0-9]+", str(query).lower())
              if t not in {"and", "the", "for", "in"}]
    if not tokens:
        return None
    for job in jobs:
        title = str(job.title).lower()
        if sum(token in title for token in tokens) >= min(2, len(tokens)):
            return job
    return None


def debug_easy_apply(args):
    """Returns process exit code, printing only non-sensitive diagnostics."""
    if (getattr(args, "portal", "linkedin") != "linkedin"
            or getattr(args, "job_url", "")
            or getattr(args, "approve_one_live_application", False)
            or getattr(args, "allow_outside_window", False)):
        print(json.dumps({
            "status": "debug_mode_conflicting_flags",
            "reason": "Use LinkedIn query/location with --debug-easy-apply-only; "
                      "omit --job-url, --approve-one-live-application and --allow-outside-window.",
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2

    try:
        profile = _safe_json(args.private_profile)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        trace_event("debug_profile_unavailable", error_type=type(exc).__name__)
        print(json.dumps({
            "status": "debug_private_profile_unavailable",
            "reason_code": type(exc).__name__,
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2

    resume_path = str(getattr(args, "resume_path", "") or "").strip()
    if not resume_path:
        try:
            from resume_store import resolve_current_resume
            resume_path = str(resolve_current_resume())
        except (OSError, ValueError):
            resume_path = ""
    # Read-only resume fact extraction; never logs personal profile values.
    if resume_path:
        try:
            from resume_facts import derive_resume_facts
            for key, value in derive_resume_facts(resume_path).items():
                if profile.get(key) in ("", None) and value not in ("", None):
                    profile[key] = value
        except (OSError, ValueError):
            pass

    config = BrowserRuntimeConfig(
        user_data_dir=args.profile_dir, headless=args.headless, slow_mo_ms=125
    )
    try:
        with PlaywrightSession(config) as runtime:
            page = runtime.page
            adapter = LinkedInBrowserAdapter(page)
            login = adapter.login_state()
            if not login.authenticated or login.needs_human_action:
                print(json.dumps({
                    "status": "debug_linkedin_session_required",
                    "reason": login.reason,
                    "attempted": 0, "confirmed": 0,
                }, sort_keys=True))
                return 4

            adapter.open_search(args.query, args.location)
            found = adapter.extract_search_results(())
            candidates = found[: max(0, min(int(args.max_jobs), 20))]
            selected = _first_matching_title(candidates, args.query)
            if selected is None:
                print(json.dumps({
                    "status": "debug_no_matching_job",
                    "discovered": len(found), "attempted": 0, "confirmed": 0,
                }, sort_keys=True))
                return 4

            # Select exactly one job; no other jobs are attempted or retried.
            trace_event("debug_easy_apply_job_selected",
                        job_key=selected.key, title=selected.title)
            bounded_goto(page, selected.url)

            result_path = ""
            outcome = "debug_entry_not_ready"
            steps_completed = 0
            try:
                entry = inspect_linkedin_application_entry(
                    page, open_easy_apply=True, open_external_apply=False
                )
                if (entry.application_type != "LINKEDIN_EASY_APPLY"
                        or entry.application_state != "FORM_READY"):
                    trace_event("debug_easy_apply_entry_blocked",
                                application_type=entry.application_type,
                                application_state=entry.application_state)
                    outcome = "debug_entry_not_ready"
                    reason = entry.application_state
                else:
                    # Explicitly never call run_linkedin_application,
                    # execute_submission, or click Review/Submit controls.
                    flow = run_safe_application_flow(
                        page, profile, resume_path=resume_path,
                        advance=True, inspect_review=False,
                        live_submission_enabled=False,
                        application_type="LINKEDIN_EASY_APPLY",
                    )
                    outcome = flow.state
                    steps_completed = flow.steps_completed
                    reason = flow.reasons[0] if flow.reasons else "debug_flow_finished"
            except Exception as exc:
                outcome = "debug_form_exception"
                reason = type(exc).__name__
                trace_event("debug_easy_apply_exception",
                            error_type=type(exc).__name__)

            result_path = capture_blocker(
                page, stage="non_submitting_debug",
                outcome=outcome, reason_code=reason,
                steps_completed=steps_completed,
            )
            hold_blocked_browser(page, getattr(args, "debug_hold_seconds", 0))
            print(json.dumps({
                "status": "easy_apply_debug_complete",
                "flow_state": outcome,
                "job_key": selected.key,
                "steps_completed": steps_completed,
                "blocker_report": result_path,
                "submission_enabled": False,
                "attempted": 0, "confirmed": 0,
            }, sort_keys=True))
            return 0
    except BrowserRuntimeUnavailable as exc:
        print(json.dumps({
            "status": "browser_runtime_unavailable",
            "reason_code": type(exc).__name__,
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2
