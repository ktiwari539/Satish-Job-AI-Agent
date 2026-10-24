"""Non-submitting, one-job LinkedIn Easy Apply diagnostic.

This workflow deliberately does NOT import a submitter or run the live batch.
It may fill a draft application and click intermediate Next and Review buttons,
but NEVER Submit or external-apply controls. It can inspect the final submit
selector without using the live submission engine or spending a pilot attempt.
"""
import json
import re
import sqlite3
import sys
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


def _portal_job_already_applied(
    page, job_url: str, *, details=None
) -> bool:
    """Check exact-job Applied status with privacy-safe evidence categories.

    An unverified status is not evidence that the job was never applied to.
    """
    try:
        target = parse_linkedin_target(job_url)
        evidence = inspect_exact_applied_status(page, target)
        status = evidence.get("status")
        applied = status == "linkedin_exact_job_applied_visible"
        ambiguous = status == "application_status_ambiguous"
        allowed = {
            "exact_job_applied_control", "exact_job_applied_badge",
            "exact_job_application_status",
        }
        kind = evidence.get("evidence_kind")
        kind = kind if kind in allowed else "none"
        decision = "applied" if applied else ("ambiguous" if ambiguous else "unverified")
        if details is not None:
            details.update(status=decision, evidence_kind=kind)
        trace_event(
            "debug_exact_job_portal_status_check",
            job_id=target.job_id,
            status=decision,
            evidence_kind=kind, easy_apply_clicked=False,
        )
        return applied
    except (ValueError, AttributeError, TypeError) as exc:
        if details is not None:
            details.update(status="unverified", evidence_kind="none")
        trace_event(
            "debug_exact_job_portal_status_check",
            status="unverified", evidence_kind="none",
            reason_code=type(exc).__name__, easy_apply_clicked=False,
        )
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


_MANUAL_REVIEW_BLOCKERS = {
    "BLOCKED_APPROVED_SCREENING_SELECTION",
    "BLOCKED_AFTER_FILL",
    "BLOCKED_REQUIRED_SCREENING_ANSWERS",
    "BLOCKED_UNVERIFIED_SCREENING_CHOICES",
    "REVIEW_VALIDATION_BLOCKED",
    "BLOCKED_UNKNOWN_REQUIRED_FIELDS",
}


def _offer_interactive_screening_recovery(
    outcome: str, *, enabled: bool, page=None, profile=None,
    profile_path="", unknown_fields=(),
) -> bool:
    """Keep the authenticated browser open for one manual correction cycle.

    The user can answer their own questions in the open browser. The agent
    never guesses an answer or clicks Submit. The terminal waits for Enter
    only when an interactive TTY explicitly requested this mode.
    """
    if not enabled or outcome not in _MANUAL_REVIEW_BLOCKERS:
        return False
    if not sys.stdin.isatty():
        trace_event("debug_manual_screening_unavailable", reason="not_a_tty")
        return False
    if (
        outcome == "BLOCKED_UNKNOWN_REQUIRED_FIELDS"
        and page is not None and isinstance(profile, dict)
        and profile_path and unknown_fields
    ):
        try:
            from answer_learning import learn_required_answers
            learned = learn_required_answers(
                page, profile, profile_path, unknown_fields,
            )
            trace_event(
                "debug_screening_answers_learned",
                question_count=learned["questions_found"],
                saved_count=learned["answers_saved"],
                answer_text_logged=False,
                question_text_logged=False,
            )
            if learned["answers_saved"] > 0:
                return True
        except (OSError, ValueError) as exc:
            trace_event(
                "debug_screening_learning_unavailable",
                reason_code=type(exc).__name__,
            )
    print(json.dumps({
        "status": "debug_manual_screening_checkpoint",
        "flow_state": outcome,
        "browser_open": True,
        "submission_enabled": False,
        "instruction": (
            "Answer the unanswered screening questions in the open LinkedIn "
            "browser, leave the application on Additional Questions, "
            "then press Enter in the terminal. The agent will click Review "
            "once; NEVER click Submit application."
        ),
    }, sort_keys=True), flush=True)
    try:
        input("After choosing your truthful screening answers, press ENTER here (agent checks Review; never Submit): ")
    except (EOFError, KeyboardInterrupt):
        trace_event("debug_manual_screening_interrupted")
        return False
    return True


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

    # A deliberately opt-in bounded autonomous diagnostic may abandon an
    # already-applied/uncertain exact job and search for a different job.
    # Without this explicit flag, an exact --job-url never switches jobs.
    smart_mode = bool(getattr(args, "smart_debug", False))
    smart_fallback_reason = ""
    skipped_exact_job_id = ""

    # Check a user-supplied exact target before accessing private files or
    # opening a browser. Debugging is non-submitting, but editing a previous
    # application draft is still an unwanted side effect.
    if target is not None:
        try:
            if _local_application_already_recorded(args, target.url):
                if smart_mode:
                    skipped_exact_job_id = target.job_id
                    smart_fallback_reason = "local_already_applied"
                    trace_event(
                        "smart_debug_fallback_search",
                        skipped_job_id=skipped_exact_job_id,
                        reason_code=smart_fallback_reason,
                        submission_enabled=False,
                    )
                    target = None
                else:
                    print(json.dumps({
                        "status": "debug_already_applied_skipped",
                        "job_id": target.job_id,
                        "attempted": 0, "confirmed": 0,
                        "browser_started": False,
                        "flow_tested": False,
                        "flow_state": "NOT_RUN_ALREADY_APPLIED",
                        "stop_stage": "local_ledger_preflight",
                        "evidence_source": "local_application_ledger",
                        "next_action": "select_unapplied_linkedin_job",
                        "steps_completed": 0, "submission_enabled": False,
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
                portal_evidence = {}
                applied = _portal_job_already_applied(
                    page, target.url, details=portal_evidence
                )
                if applied and smart_mode:
                    skipped_exact_job_id = target.job_id
                    smart_fallback_reason = "portal_already_applied"
                    trace_event(
                        "smart_debug_fallback_search",
                        skipped_job_id=skipped_exact_job_id,
                        reason_code=smart_fallback_reason,
                        submission_enabled=False,
                    )
                    target = None
                if applied and not smart_mode:
                    summary = {
                        "status": "debug_portal_already_applied_skipped",
                        "job_id": target.job_id,
                        "attempted": 0, "confirmed": 0,
                        "easy_apply_opened": False,
                        "flow_tested": False,
                        "flow_state": "NOT_RUN_ALREADY_APPLIED",
                        "stop_stage": "linkedin_applied_preflight",
                        "evidence_source": "linkedin_exact_job_status",
                        "evidence_kind": portal_evidence.get(
                            "evidence_kind", "not_exposed_by_test_stub"
                        ),
                        "next_action": "select_unapplied_linkedin_job",
                        "steps_completed": 0, "submission_enabled": False,
                    }
                    trace_event("debug_job_skip_decision", **summary)
                    print(json.dumps(summary, sort_keys=True))
                    return 0
                if (target is not None and smart_mode
                        and portal_evidence.get("status") == "ambiguous"):
                    skipped_exact_job_id = target.job_id
                    smart_fallback_reason = "portal_status_ambiguous"
                    trace_event(
                        "smart_debug_fallback_search",
                        skipped_job_id=skipped_exact_job_id,
                        reason_code=smart_fallback_reason,
                        submission_enabled=False,
                    )
                    target = None
                if (target is not None
                        and portal_evidence.get("status") == "ambiguous"):
                    summary = {
                        "status": "debug_ambiguous_application_status_blocked",
                        "job_id": target.job_id,
                        "flow_state": "NOT_RUN_APPLIED_STATUS_AMBIGUOUS",
                        "stop_stage": "linkedin_applied_preflight",
                        "evidence_source": "linkedin_unscoped_application_status",
                        "next_action": "verify_applied_status_manually_or_select_another_job",
                        "flow_tested": False,
                        "easy_apply_opened": False,
                        "submission_enabled": False,
                        "attempted": 0, "confirmed": 0,
                    }
                    trace_event("debug_job_skip_decision", **summary)
                    print(json.dumps(summary, sort_keys=True))
                    return 4
                if target is not None:
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
            if target is None:
                adapter.open_search(args.query, args.location)
                found = adapter.extract_search_results(())
                candidates = found[: max(0, min(int(args.max_jobs), 20))]
                checked = 0
                discovered = len(found)
                # Discover Easy Apply entries without opening an application
                # to any job until exactly one selected candidate is known.
                for candidate in candidates:
                    # Never loop back to the exact job whose Applied status
                    # caused this bounded search fallback.
                    try:
                        candidate_id = parse_linkedin_target(candidate.url).job_id
                    except ValueError:
                        continue
                    if skipped_exact_job_id and candidate_id == skipped_exact_job_id:
                        skipped_applied += 1
                        trace_event(
                            "smart_debug_skipped_original_job",
                            job_id=candidate_id,
                            reason_code=smart_fallback_reason,
                        )
                        continue
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
                        candidate_status = {}
                        already_applied = _portal_job_already_applied(
                            page, candidate.url, details=candidate_status
                        )
                        if already_applied or candidate_status.get("status") == "ambiguous":
                            skipped_applied += 1
                            trace_event(
                                "debug_existing_portal_application_skipped",
                                job_key=candidate.key,
                                status=candidate_status.get("status", "applied"),
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
                    "smart_mode": smart_mode,
                    "smart_fallback_reason": smart_fallback_reason,
                    "next_action": (
                        "no_safe_unapplied_easy_apply_listing_found"
                        if smart_mode else "inspect_search_candidates"
                    ),
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
            last_unknown_fields = ()
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
                    last_unknown_fields = tuple(getattr(flow, "unknown_required_fields", ()))
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

            if _offer_interactive_screening_recovery(
                outcome,
                enabled=bool(getattr(args, "debug_interactive", False)),
                page=page, profile=profile,
                profile_path=args.private_profile,
                unknown_fields=last_unknown_fields,
            ):
                # Retry only a non-submitting read/fill/Review inspection
                # after the user has explicitly corrected their own answers.
                # No automatic guesses and no click on final Submit.
                try:
                    resumed = run_safe_application_flow(
                        page, profile, resume_path=resume_path,
                        advance=True, inspect_review=True,
                        live_submission_enabled=False,
                        application_type="LINKEDIN_EASY_APPLY",
                        verified_easy_apply_modal=True,
                    )
                    outcome = resumed.state
                    steps_completed += resumed.steps_completed
                    reason = next(
                        (value for value in resumed.reasons
                         if value != "live_submission_disabled"),
                        resumed.state,
                    )
                    trace_event(
                        "debug_manual_screening_recheck",
                        state=outcome,
                        steps_completed=steps_completed,
                        submission_enabled=False,
                        submit_clicks=0,
                    )
                    if outcome == "REVIEW_INSPECTED":
                        final_proof = bool(
                            _active_dialog_root(page)
                            or _verified_inline_linkedin_final_review(page)
                        )
                        if final_proof:
                            submit, _ = _visible_submit_control(
                                page, "LINKEDIN_EASY_APPLY"
                            )
                            submit_resolver_ready = submit is not None
                except Exception as exc:
                    outcome = "debug_manual_recheck_exception"
                    reason = type(exc).__name__
                    trace_event(
                        "debug_manual_screening_recheck_failed",
                        error_type=type(exc).__name__,
                    )

            result_path = capture_blocker(
                page, stage="non_submitting_debug",
                outcome=outcome, reason_code=reason,
                steps_completed=steps_completed,
            )
            hold_blocked_browser(page, getattr(args, "debug_hold_seconds", 0))
            # A diagnostic run is not a successful application-flow check
            # merely because it terminated without raising an exception.
            # Form-entry failures and blocked navigation use a nonzero exit.
            review_reached = outcome == "REVIEW_INSPECTED"
            trace_event(
                "debug_acceptance_result",
                accepted=review_reached,
                form_steps_completed=steps_completed,
                failure_reason="" if review_reached else outcome,
                submission_enabled=False,
            )
            print(json.dumps({
                "status": (
                    "easy_apply_debug_review_reached"
                    if review_reached else "easy_apply_debug_blocked"
                ),
                "flow_state": outcome,
                "job_key": selected.key,
                "smart_mode": smart_mode,
                "smart_fallback_reason": smart_fallback_reason,
                "discovered": discovered,
                "previewed": checked,
                "skipped_applied": skipped_applied,
                "steps_completed": steps_completed,
                "submit_resolver_ready": submit_resolver_ready,
                "blocker_report": result_path,
                "submission_enabled": False,
                "flow_tested": True,
                "flow_acceptance": "PASSED" if review_reached else "BLOCKED",
                "stop_stage": (
                    "review_inspection" if review_reached else
                    "application_entry_or_form_navigation"
                ),
                "next_action": (
                    "verify_resume_and_fields_before_pilot"
                    if review_reached else "inspect_application_blocker_report"
                ),
                "attempted": 0, "confirmed": 0,
            }, sort_keys=True))
            return 0 if review_reached else 4
    except BrowserRuntimeUnavailable as exc:
        print(json.dumps({
            "status": "browser_runtime_unavailable",
            "reason_code": type(exc).__name__,
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2
