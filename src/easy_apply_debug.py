"""Non-submitting, one-job LinkedIn Easy Apply diagnostic.

This workflow deliberately does NOT import a submitter or run the live batch.
It may fill a draft application and click intermediate Next and Review buttons,
but NEVER Submit or external-apply controls. It can inspect the final submit
selector without using the live submission engine or spending a pilot attempt.
"""
import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from agent_trace import trace_event
from apply_inspection import inspect_linkedin_application_entry
from application_flow import run_safe_application_flow
from browser_portals import LinkedInBrowserAdapter
from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession
from live_blocker_capture import capture_blocker, hold_blocked_browser
from linkedin_exact_job import parse_linkedin_target, ensure_exact_target
from linkedin_applied_status import inspect_exact_applied_status
from submission_engine import (
    _active_dialog_root, _visible_submit_control,
    _verified_inline_linkedin_final_review,
)
from navigation import bounded_goto


def _safe_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("private_profile_must_be_object")
    return value


def _portal_job_already_applied(page, job_url: str) -> bool:
    """Return positive exact-job LinkedIn evidence, never assume not applied."""
    try:
        target = parse_linkedin_target(job_url)
        evidence = inspect_exact_applied_status(page, target)
        return evidence.get("status") == "linkedin_exact_job_applied_visible"
    except (ValueError, AttributeError, TypeError):
        return False


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


def _local_application_already_recorded(args, job_url: str) -> bool:
    """Read the actual application ledger without creating/migrating the DB.

    When a real DB path is configured, unreadable storage is a blocker rather
    than permission to open a previously submitted application.
    """
    db_path = getattr(args, "db", None)
    if db_path is None:
        # Compatibility for existing minimal test fixtures. The real CLI
        # supplies --db by default.
        return False
    target = parse_linkedin_target(job_url)
    with sqlite3.connect(Path(db_path).expanduser().resolve().as_uri() + "?mode=ro",
                         uri=True) as conn:
        match = conn.execute(
            """SELECT 1 FROM applications
               WHERE source = 'linkedin'
                 AND (external_id = ? OR url = ?)
                 AND status IN ('APPLIED', 'CONFIRMED') LIMIT 1""",
            (target.job_id, target.url),
        ).fetchone()
    return match is not None


def debug_easy_apply(args):
    """Returns process exit code, printing only non-sensitive diagnostics."""
    if (getattr(args, "portal", "linkedin") != "linkedin"
            or getattr(args, "approve_one_live_application", False)
            or getattr(args, "allow_outside_window", False)):
        print(json.dumps({
            "status": "debug_mode_conflicting_flags",
            "reason": "Use LinkedIn --debug-easy-apply-only without live approval or quota overrides.",
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2

    try:
        target = (
            parse_linkedin_target(args.job_url)
            if getattr(args, "job_url", "") else None
        )
    except ValueError as exc:
        print(json.dumps({
            "status": "invalid_exact_job_target", "reason": str(exc),
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2

    # Check a user-supplied exact target before accessing private files or
    # opening a browser. Debugging is non-submitting, but editing a previous
    # application draft is still an unwanted side effect.
    if target is not None:
        try:
            if _local_application_already_recorded(args, target.url):
                print(json.dumps({
                    "status": "debug_already_applied_skipped",
                    "job_id": target.job_id,
                    "attempted": 0, "confirmed": 0,
                    "browser_started": False,
                }, sort_keys=True))
                return 0
        except (sqlite3.Error, ValueError, OSError) as exc:
            print(json.dumps({
                "status": "debug_ledger_unavailable",
                "reason_code": type(exc).__name__,
                "attempted": 0, "confirmed": 0,
            }, sort_keys=True))
            return 4

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

            selected = None
            skipped_applied = 0
            if target is not None:
                # The user already supplied an exact, known Easy Apply job.
                # Do not perform a broad search or choose another listing.
                bounded_goto(page, target.url)
                ensure_exact_target(page, target)
                if _portal_job_already_applied(page, target.url):
                    print(json.dumps({
                        "status": "debug_portal_already_applied_skipped",
                        "job_id": target.job_id,
                        "attempted": 0, "confirmed": 0,
                        "easy_apply_opened": False,
                    }, sort_keys=True))
                    return 0
                preview = inspect_linkedin_application_entry(
                    page, open_easy_apply=False, open_external_apply=False
                )
                if (preview.application_type == "LINKEDIN_EASY_APPLY"
                        and preview.application_state in ("APPLICATION_ENTRY_FOUND", "FORM_READY")):
                    selected = SimpleNamespace(
                        key="linkedin:" + target.job_id,
                        title="exact_job_debug_target",
                        url=target.url,
                    )
                checked = 1
                discovered = 1
            else:
                adapter.open_search(args.query, args.location)
                found = adapter.extract_search_results(())
                candidates = found[: max(0, min(int(args.max_jobs), 20))]
                checked = 0
                discovered = len(found)
                # Discover Easy Apply entries without opening an application
                # to any job until exactly one selected candidate is known.
                for candidate in candidates:
                    if _first_matching_title((candidate,), args.query) is None:
                        continue
                    try:
                        if _local_application_already_recorded(args, candidate.url):
                            skipped_applied += 1
                            trace_event(
                                "debug_existing_application_skipped",
                                job_key=candidate.key,
                            )
                            continue
                    except ValueError:
                        # A candidate with an unrecognized URL must never
                        # become the active Easy Apply debug target.
                        continue
                    except (sqlite3.Error, OSError) as exc:
                        print(json.dumps({
                            "status": "debug_ledger_unavailable",
                            "reason_code": type(exc).__name__,
                            "attempted": 0, "confirmed": 0,
                        }, sort_keys=True))
                        return 4
                    checked += 1
                    try:
                        bounded_goto(page, candidate.url)
                        if _portal_job_already_applied(page, candidate.url):
                            skipped_applied += 1
                            trace_event(
                                "debug_existing_portal_application_skipped",
                                job_key=candidate.key,
                            )
                            continue
                        preview = inspect_linkedin_application_entry(
                            page, open_easy_apply=False, open_external_apply=False
                        )
                    except Exception as exc:
                        trace_event("debug_easy_apply_preview_failed",
                                    error_type=type(exc).__name__)
                        continue
                    if (preview.application_type == "LINKEDIN_EASY_APPLY"
                            and preview.application_state in ("APPLICATION_ENTRY_FOUND", "FORM_READY")):
                        selected = candidate
                        break
            if selected is None:
                print(json.dumps({
                    "status": "debug_no_easy_apply_entry",
                    "discovered": discovered, "previewed": checked,
                    "skipped_applied": skipped_applied,
                    "attempted": 0, "confirmed": 0,
                }, sort_keys=True))
                return 4
            trace_event("debug_easy_apply_job_selected",
                        job_key=selected.key, title=selected.title)
            # We are already on this verified job page. Open its form once.

            result_path = ""
            outcome = "debug_entry_not_ready"
            steps_completed = 0
            submit_resolver_ready = False
            try:
                entry = inspect_linkedin_application_entry(
                    page, open_easy_apply=True, open_external_apply=False
                )
                if (entry.application_type != "LINKEDIN_EASY_APPLY"
                        or entry.application_state != "FORM_READY"):
                    trace_event("debug_easy_apply_entry_blocked",
                                application_type=entry.application_type,
                                application_state=entry.application_state,
                                reason_code=entry.reason or entry.application_state)
                    outcome = entry.reason or entry.application_state
                    reason = outcome
                else:
                    # Review is a non-submitting navigation step. Inspect
                    # the final review page and stop before Submit. This
                    # debugger never calls run_linkedin_application or any
                    # submission function, regardless of the review outcome.
                    flow = run_safe_application_flow(
                        page, profile, resume_path=resume_path,
                        advance=True, inspect_review=True,
                        live_submission_enabled=False,
                        application_type="LINKEDIN_EASY_APPLY",
                        verified_easy_apply_modal=True,
                    )
                    outcome = flow.state
                    steps_completed = flow.steps_completed
                    reason = next((item for item in flow.reasons if item != "live_submission_disabled"), flow.state)
                    if flow.state == "REVIEW_INSPECTED":
                        # Read-only parity check of the *actual submission*
                        # resolver against LinkedIn's final page. Never click.
                        final_proof = bool(
                            _active_dialog_root(page)
                            or _verified_inline_linkedin_final_review(page)
                        )
                        if final_proof:
                            submit, _ = _visible_submit_control(
                                page, "LINKEDIN_EASY_APPLY"
                            )
                            submit_resolver_ready = submit is not None
                        trace_event(
                            "debug_final_submit_selector_verified",
                            valid_final_review=final_proof,
                            submit_resolver_ready=submit_resolver_ready,
                            submit_clicks=0,
                        )
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
                "submit_resolver_ready": submit_resolver_ready,
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
