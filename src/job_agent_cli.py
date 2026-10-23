import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from agent_trace import RunTracer, get_active_tracer, reset_active_tracer, set_active_tracer, trace_event, trace_step
from application_runner import ApplicationAttempt, run_application_batch
from automation_policy import load_automation_policy
from browser_auth import BrowserAuthCredentials, execute_linkedin_sign_in
from browser_portals import LinkedInBrowserAdapter, NaukriBrowserAdapter, classify_linkedin_probe, classify_naukri_probe
from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession
from jd_enrichment import enrich_job_with_page
from jd_enrichment import EnrichmentResult
from linkedin_exact_job import parse_linkedin_target, inspect_exact_linkedin_job, ensure_exact_target
from linkedin_public_metadata import fetch_public_exact_linkedin_job, exact_public_job_url
from linkedin_applied_status import inspect_exact_applied_status
from local_profile_city import read_applicant_city, set_applicant_city
from linkedin_selected_search import inspect_selected_search_job
from linkedin_page_diagnostics import diagnose_linkedin_search_page
from easy_apply_debug import debug_easy_apply
from live_blocker_capture import capture_blocker, hold_blocked_browser
from matcher import score_profile
from policy import evaluate_eligibility
from linkedin_application import run_linkedin_application
from local_credentials import load_first_portal_credentials, load_portal_credentials
from models import CandidateProfile
from navigation import bounded_goto
from quota import evaluate_application_quota
from resume_facts import derive_resume_facts
from resume_store import resolve_current_resume
from store import JobStore


def _load_json(path: str) -> dict:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(path)
    return json.loads(target.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Job AI Agent end-to-end through confirmed submission."
    )
    parser.add_argument("--profile", default="config/qa_profile.json")
    parser.add_argument("--private-profile", default="data/private_profile.json")
    parser.add_argument("--policy", default="config/automation_policy.production.json")
    parser.add_argument("--credentials-file", default="data/portal_credentials.json")
    parser.add_argument("--profile-dir", default="browser-profile")
    parser.add_argument("--db", default="data/jobs.db")
    parser.add_argument("--report", default="data/application_report.json")
    parser.add_argument(
        "--resume-path",
        default=os.environ.get("JOB_AGENT_RESUME_PATH", ""),
        help=(
            "Optional explicit resume path. If omitted, the agent uses its own "
            "trusted resume from ~/.satish-job-ai-agent/resume."
        ),
    )
    parser.add_argument("--portal", choices=("linkedin", "naukri"), default="linkedin")
    parser.add_argument("--query", default="Customer Success Manager")
    parser.add_argument(
        "--location", default="India",
        help="JOB SEARCH geography only; does not change applicant's city in the private profile.",
    )
    parser.add_argument("--max-jobs", type=int, default=20)
    parser.add_argument(
        "--job-url", default="",
        help="Target exactly one LinkedIn job ID, either /jobs/view/ID or a search-results URL with currentJobId.",
    )
    parser.add_argument(
        "--public-job-url", default="",
        help="Optional same-job-ID public LinkedIn posting URL for strict JD scoring when the signed-in DOM omits job details. Never authorizes submission.",
    )
    parser.add_argument(
        "--check-applied-status-only", action="store_true",
        help="Read-only check of the exact LinkedIn job's Applied indicator. Never opens Easy Apply, clicks Submit, or updates DB.",
    )
    parser.add_argument(
        "--set-profile-city", default="",
        help="Update the applicant's current city in the local private profile only. Does not open a browser or submit.",
    )
    parser.add_argument(
        "--check-profile-city-only", action="store_true",
        help="Read the applicant's local, gitignored private-profile location without opening a browser or submitting.",
    )
    parser.add_argument(
        "--inspect-job-only", action="store_true",
        help="Read-only exact-job quality check. Does not access private profile, resume, or submit.",
    )
    parser.add_argument(
        "--diagnose-linkedin-page", action="store_true",
        help="Read-only selected search-page structure probe. No resume, profile, application, or clicks.",
    )
    parser.add_argument(
        "--debug-hold-seconds", type=int, default=0,
        help="After a blocked live application, keep the browser open for 0-120 seconds; no additional actions.",
    )
    parser.add_argument(
        "--debug-easy-apply-only", action="store_true",
        help="Non-submitting Easy Apply form debugging outside application windows. "
             "May fill a draft and click Next/Review, but never final Submit.",
    )
    parser.add_argument(
        "--debug-interactive", action="store_true",
        help=(
            "With --debug-easy-apply-only and an interactive terminal, keep the "
            "LinkedIn browser open when a screening answer is blocked. "
            "You may answer in the browser and press Enter to rerun a "
            "non-submitting Review check. Never clicks final Submit."
        ),
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--approve-one-live-application",
        action="store_true",
        help=(
            "Explicit approval for ONE submission attempt in this run. "
            "A failed or unconfirmed attempt still consumes the pilot limit."
        ),
    )
    parser.add_argument("--trace-dir", default="data/agent_runs")
    parser.add_argument("--heartbeat-seconds", type=float, default=5.0)
    parser.add_argument(
        "--testing-mode",
        action="store_true",
        help=(
            "Explicit single-job QA pilot outside production time windows. "
            "Still requires --approve-one-live-application, qualified exact LinkedIn "
            "--job-url, and at most one attempted submission. Production schedule remains enforced."
        ),
    )
    parser.add_argument(
        "--allow-outside-window",
        action="store_true",
        help="Legacy controlled QA override; prefer --testing-mode for exact-job tests.",
    )
    return parser.parse_args()


def _application_reason(run) -> str:
    if run.submission is not None:
        return run.submission.reason or run.submission.state
    if run.flow is not None:
        parts = [run.flow.state]
        parts.extend(run.flow.reasons)
        parts.extend(run.flow.unknown_required_fields)
        parts.extend(run.flow.missing_profile_values)
        parts.extend(run.flow.review_mismatches)
        return "|".join(str(value) for value in parts if value)
    return run.entry.reason or run.entry.application_state



def _pilot_result(confirmed_count: int) -> tuple[str, int]:
    """A pilot is successful only with exactly one verified submission."""
    return ("pilot_confirmed", 0) if confirmed_count == 1 else ("pilot_unconfirmed", 5)

def _pilot_job_counts(search_results: int, considered: int) -> dict:
    """Separate discovered search hits from evaluated batch entries."""
    if not 0 <= considered <= search_results:
        raise ValueError("invalid_pilot_job_counts")
    return {"discovered": search_results, "considered": considered}



def _pilot_quota_preflight(
    policy, store, *, allow_outside_window: bool = False,
    testing_mode: bool = False, now=None,
):
    """Reject a blocked pilot before reading private files or starting Chrome.

    None means execution may proceed to normal per-job quota enforcement.
    A structured blocked result never enables or submits any application.
    """
    if testing_mode:
        # Testing ignores *time windows*, not the daily success cap. Every
        # individual test still needs a separate approval and the runner
        # enforces max_application_attempts=1, even for uncertain outcomes.
        quota = evaluate_application_quota(policy, store, now=now)
        trace_event(
            "testing_mode_preflight", allowed=quota.remaining_day > 0,
            daily_confirmed=quota.daily_confirmed,
            remaining_day=quota.remaining_day,
            production_time_window_ignored=True,
        )
        if quota.remaining_day <= 0:
            return {
                "status": "daily_success_cap_reached",
                "stage": "testing_mode_preflight",
                "attempted": 0, "confirmed": 0,
                "remaining_day": quota.remaining_day,
                "timezone": policy.timezone,
            }
        return None
    if allow_outside_window:
        return None
    quota = evaluate_application_quota(policy, store, now=now)
    trace_event(
        "quota_preflight", allowed=quota.allowed, reason=quota.reason,
        active_window=quota.active_window, remaining_window=quota.remaining_window,
        remaining_day=quota.remaining_day,
    )
    if quota.allowed:
        return None
    result = {
        "status": quota.reason,
        "stage": "quota_preflight",
        "attempted": 0,
        "confirmed": 0,
        "discovered": 0,
        "considered": 0,
        "timezone": policy.timezone,
    }
    if quota.reason == "outside_application_window":
        key, start, end = policy.next_window(now)
        result.update(
            next_window=key,
            next_window_start=start.isoformat(),
            next_window_end=end.isoformat(),
        )
    return result


def _check_local_profile_city(args: argparse.Namespace) -> int:
    """Applicant city is in the PRIVATE form profile, NOT --location search."""
    location = read_applicant_city(args.private_profile)
    print(json.dumps({
        "status": "profile_city_configured" if location else "profile_city_missing",
        "applicant_city": location if location else "",
        "source": "private_profile.location",
        "search_location_is_separate": True,
        "attempted": 0, "confirmed": 0,
    }, sort_keys=True))
    return 0 if location else 4


def _check_linkedin_applied_status(args: argparse.Namespace) -> int:
    """Read-only exact-ID status: missing evidence does NOT mean not applied."""
    if (getattr(args, "portal", "linkedin") != "linkedin"
            or getattr(args, "approve_one_live_application", False)):
        print(json.dumps({
            "status": "read_only_status_conflicting_flags",
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2
    try:
        target = parse_linkedin_target(getattr(args, "job_url", ""))
    except ValueError as exc:
        print(json.dumps({
            "status": "invalid_exact_job_target", "reason": str(exc),
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2
    runtime_config = BrowserRuntimeConfig(
        user_data_dir=args.profile_dir, headless=args.headless, slow_mo_ms=125,
    )
    with PlaywrightSession(runtime_config) as runtime:
        page = runtime.page
        session = LinkedInBrowserAdapter(page).login_state()
        if not session.authenticated or session.needs_human_action:
            print(json.dumps({
                "status": "linkedin_session_required", "reason": session.reason,
                "attempted": 0, "confirmed": 0,
            }, sort_keys=True))
            return 4
        bounded_goto(page, target.url)
        ensure_exact_target(page, target)
        page.wait_for_timeout(1200)
        result = inspect_exact_applied_status(page, target)
        trace_event(
            "read_only_exact_applied_status_checked", job_id=target.job_id,
            status=result["status"],
            evidence_kind=result.get("evidence_kind", ""),
        )
    print(json.dumps({
        "job_id": target.job_id,
        "attempted": 0,
        "confirmed": 0,
        "no_submission_actions": True,
        "db_modified": False,
        **result,
    }, sort_keys=True))
    return 0 if result["status"] == "linkedin_exact_job_applied_visible" else 4


def _diagnose_one_linkedin_page(args: argparse.Namespace) -> int:
    """No application or user-data reads. Diagnose the live Chrome DOM."""
    try:
        if getattr(args, "portal", "linkedin") != "linkedin":
            raise ValueError("diagnosis_supported_on_linkedin_only")
        target = parse_linkedin_target(getattr(args, "job_url", ""))
    except ValueError as exc:
        print(json.dumps({
            "status": "invalid_exact_job_target", "reason": str(exc),
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2
    runtime_config = BrowserRuntimeConfig(
        user_data_dir=args.profile_dir, headless=args.headless, slow_mo_ms=125,
    )
    with PlaywrightSession(runtime_config) as runtime:
        page = runtime.page
        login = LinkedInBrowserAdapter(page).login_state()
        if not login.authenticated or login.needs_human_action:
            print(json.dumps({
                "status": "linkedin_session_required", "reason": login.reason,
                "attempted": 0, "confirmed": 0,
            }, sort_keys=True))
            return 4
        try:
            diagnosis = diagnose_linkedin_search_page(
                page, target, source_url=args.job_url,
                keywords=getattr(args, "query", "Customer Success Manager"),
            )
        except ValueError as exc:
            print(json.dumps({
                "status": "linkedin_page_diagnosis_blocked",
                "reason": str(exc), "job_id": target.job_id,
                "attempted": 0, "confirmed": 0,
            }, sort_keys=True))
            return 4
    print(json.dumps({
        "status": "linkedin_page_diagnosis_complete",
        "job_id": target.job_id, "page_signals": diagnosis,
        "attempted": 0, "confirmed": 0,
    }, sort_keys=True))
    return 0


def _inspect_one_linkedin_job(args: argparse.Namespace) -> int:
    """Read-only job viability check. Never calls the application engine."""
    try:
        if getattr(args, "portal", "linkedin") != "linkedin":
            raise ValueError("exact_job_supported_on_linkedin_only")
        target = parse_linkedin_target(getattr(args, "job_url", ""))
    except ValueError as exc:
        print(json.dumps({"status": "invalid_exact_job_target", "reason": str(exc),
                          "attempted": 0, "confirmed": 0}, sort_keys=True))
        return 2
    public_url = str(getattr(args, "public_job_url", "") or "").strip()
    if public_url:
        try:
            public_url = exact_public_job_url(public_url, target.job_id)
        except ValueError as exc:
            print(json.dumps({"status": "public_job_url_rejected", "reason": str(exc),
                              "attempted": 0, "confirmed": 0}, sort_keys=True))
            return 2

    profile = CandidateProfile.from_dict(_load_json(args.profile))
    store = JobStore(args.db)
    runtime_config = BrowserRuntimeConfig(
        user_data_dir=args.profile_dir, headless=args.headless, slow_mo_ms=125,
    )
    with PlaywrightSession(runtime_config) as runtime:
        page = runtime.page
        session = LinkedInBrowserAdapter(page).login_state()
        if not session.authenticated or session.needs_human_action:
            print(json.dumps({
                "status": "linkedin_session_required",
                "reason": session.reason,
                "attempted": 0, "confirmed": 0,
            }, sort_keys=True))
            return 4

        inspection_route = "direct_job_view"
        job = None
        try:
            job = inspect_exact_linkedin_job(page, target, profile.skill_taxonomy)
        except ValueError as exc:
            reason = str(exc)
            if public_url and reason.startswith(("exact_job_metadata_unverified:", "exact_job_description_missing_or_short")):
                try:
                    job = fetch_public_exact_linkedin_job(
                        public_url, target, profile.skill_taxonomy
                    )
                    inspection_route = "same_id_verified_public_linkedin"
                    trace_event("exact_job_public_metadata_verified",
                                job_id=target.job_id,
                                description_length=len(job.description),
                                required_skills_count=len(job.required_skills))
                except ValueError as fallback:
                    reason += "|public_fallback:" + str(fallback)
            # Only the read-only inspection may try the original search UI.
            # The live submit path remains on the canonical job route until
            # its exact-ID application entry has been separately verified.
            if (
                job is None and not public_url
                and reason.startswith("exact_job_metadata_unverified:")
                and reason.endswith((":no_job_details_in_dom", ":empty_or_unrendered_page"))
            ):
                trace_event("exact_job_read_only_search_fallback", job_id=target.job_id)
                try:
                    job = inspect_selected_search_job(
                        page, target, profile.skill_taxonomy,
                        keywords=getattr(args, "query", "Customer Success Manager"),
                        source_url=getattr(args, "job_url", ""),
                    )
                    inspection_route = "verified_search_result"
                except ValueError as followup:
                    reason += "|search_fallback:" + str(followup)
            if job is None:
                print(json.dumps({
                    "status": "exact_job_inspection_blocked",
                    "reason": reason,
                    "job_id": target.job_id,
                    "attempted": 0, "confirmed": 0,
                }, sort_keys=True))
                return 4

    match = score_profile(profile, job, threshold=75)
    eligibility = evaluate_eligibility(profile, job)
    duplicate = store.is_recent_similar_application(job, cooldown_days=90)
    sufficient_skill_evidence = len({skill.casefold() for skill in job.required_skills}) >= 3
    qualified = (
        match.decision == "APPLY"
        and sufficient_skill_evidence
        and eligibility.eligible
        and not duplicate
    )
    result = {
        "status": (
            "exact_job_qualified_for_pilot" if qualified and inspection_route in ("direct_job_view", "same_id_verified_public_linkedin")
            else "exact_job_qualified_read_only" if qualified
            else "exact_job_not_qualified"
        ),
        "inspection_route": inspection_route,
        "live_pilot_ready": bool(qualified and inspection_route in ("direct_job_view", "same_id_verified_public_linkedin")),
        "job_id": job.external_id,
        "job_url": job.url,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "jd_length": len(job.description),
        "extracted_jd_skill_count": len(job.required_skills),
        "match_score": match.score,
        "skill_evidence_sufficient": sufficient_skill_evidence,
        "eligible": eligibility.eligible,
        "eligibility_reasons": list(eligibility.reasons),
        "duplicate": duplicate,
        "attempted": 0,
        "confirmed": 0,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if qualified else 4


def _run(args: argparse.Namespace) -> int:
    trace_event("configuration_load_start")
    if getattr(args, "set_profile_city", ""):
        try:
            city = set_applicant_city(args.private_profile, args.set_profile_city)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({
                "status": "profile_city_update_failed",
                "reason_code": type(exc).__name__,
                "attempted": 0, "confirmed": 0,
            }, sort_keys=True))
            return 2
        print(json.dumps({
            "status": "profile_city_updated", "applicant_city": city,
            "source": "private_profile.location", "attempted": 0, "confirmed": 0,
            "no_browser_actions": True,
        }, sort_keys=True))
        return 0
    if getattr(args, "check_profile_city_only", False):
        return _check_local_profile_city(args)
    if getattr(args, "check_applied_status_only", False):
        return _check_linkedin_applied_status(args)
    if getattr(args, "debug_interactive", False) and not getattr(args, "debug_easy_apply_only", False):
        print(json.dumps({
            "status": "debug_interactive_requires_easy_apply_debug",
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2
    if getattr(args, "debug_easy_apply_only", False):
        return debug_easy_apply(args)
    if getattr(args, "diagnose_linkedin_page", False):
        return _diagnose_one_linkedin_page(args)
    if getattr(args, "inspect_job_only", False):
        return _inspect_one_linkedin_job(args)
    exact_target = None
    if getattr(args, "job_url", ""):
        try:
            if getattr(args, "portal", "linkedin") != "linkedin":
                raise ValueError("exact_job_supported_on_linkedin_only")
            exact_target = parse_linkedin_target(args.job_url)
            if getattr(args, "public_job_url", ""):
                exact_public_job_url(args.public_job_url, exact_target.job_id)
        except ValueError as exc:
            print(json.dumps({"status": "invalid_exact_job_target",
                              "reason": str(exc), "attempted": 0, "confirmed": 0},
                             sort_keys=True))
            return 2
    testing_mode = bool(getattr(args, "testing_mode", False))
    if testing_mode and exact_target is None:
        print(json.dumps({
            "status": "testing_mode_requires_exact_linkedin_job",
            "reason": "Testing-time live submissions require a single verified --job-url.",
            "attempted": 0, "confirmed": 0,
        }, sort_keys=True))
        return 2
    if testing_mode:
        trace_event(
            "execution_mode_selected", execution_mode="testing",
            production_time_windows_enforced=False,
            max_application_attempts=1,
        )
    else:
        trace_event(
            "execution_mode_selected", execution_mode="production",
            production_time_windows_enforced=not bool(
                getattr(args, "allow_outside_window", False)
            ),
            max_application_attempts=1,
        )
    if not getattr(args, "approve_one_live_application", False):
        print(json.dumps({
            "status": "single_pilot_approval_required",
            "reason": "Explicit --approve-one-live-application required; scheduled or accidental runs remain non-submitting.",
            "submitted": 0,
            "confirmed": 0,
        }, sort_keys=True))
        return 3
    # Preflight cannot depend on resume, credentials, profile, or Chrome.
    # It blocks repeated early launches in milliseconds instead of searching
    # LinkedIn before the existing per-job quota stops the run.
    policy = load_automation_policy(args.policy)
    if not policy.live_submission_enabled:
        print(json.dumps({
            "status": "live_submission_disabled",
            "policy": args.policy,
        }, sort_keys=True))
        return 3
    store = JobStore(args.db)
    preflight = _pilot_quota_preflight(
        policy, store,
        allow_outside_window=bool(getattr(args, "allow_outside_window", False)),
        testing_mode=testing_mode,
    )
    if preflight is not None:
        print(json.dumps(preflight, sort_keys=True))
        return 5
    public_profile = CandidateProfile.from_dict(_load_json(args.profile))
    private_profile = _load_json(args.private_profile)

    raw_resume_path = str(args.resume_path or "").strip()
    if raw_resume_path:
        resume = Path(raw_resume_path).expanduser()
        if not resume.exists() or not resume.is_file():
            print(json.dumps({
                "status": "invalid_resume_path",
                "resume_path": str(resume),
                "reason": "Resume path must point to an existing file, not a directory.",
            }, sort_keys=True))
            return 2
        args.resume_path = str(resume.resolve())
        trace_event("resume_resolved", source="explicit_path", resume_path=args.resume_path)
    else:
        try:
            resume = resolve_current_resume()
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({
                "status": "agent_resume_not_configured",
                "reason": str(exc),
                "setup_command": "python src/resume_store.py import '/full/path/to/resume.pdf'",
"resume_vault": "~/.satish-job-ai-agent/resume",
            }, sort_keys=True))
            return 2
        args.resume_path = str(resume)
        trace_event("resume_resolved", source="agent_vault", resume_path=args.resume_path)

    derived_facts = derive_resume_facts(args.resume_path)
    added_fact_keys = []
    for key, value in derived_facts.items():
        if private_profile.get(key) in (None, "") and value not in (None, ""):
            private_profile[key] = value
            added_fact_keys.append(key)
    trace_event(
        "resume_fact_derivation",
        derived_keys=sorted(derived_facts.keys()),
        added_to_private_profile=sorted(added_fact_keys),
    )

    external_credentials = None
    try:
        fallback = ("external_default", "linkedin") if policy.allow_configured_password_reuse else ("external_default",)
        external_credentials = load_first_portal_credentials(args.credentials_file, fallback)
        trace_event(
            "external_account_credentials_ready",
            configured=True,
            reuse_allowed=policy.allow_configured_password_reuse,
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        trace_event(
            "external_account_credentials_ready",
            configured=False,
            reason=str(exc),
        )

    runtime_config = BrowserRuntimeConfig(
        user_data_dir=args.profile_dir,
        headless=args.headless,
        slow_mo_ms=125,
    )

    try:
        with PlaywrightSession(runtime_config) as runtime:
            page = runtime.page
            portal = getattr(args, 'portal', 'linkedin')
            adapter = LinkedInBrowserAdapter(page) if portal == 'linkedin' else NaukriBrowserAdapter(page)

            with trace_step(f"{portal}_session_check"):
                login = adapter.login_state()
            trace_event(
                "portal_session_state",
                portal=portal,
                authenticated=login.authenticated,
                needs_human_action=login.needs_human_action,
                reason=login.reason,
                current_url=str(getattr(page, "url", "") or ""),
            )

            if login.needs_human_action:
                print(json.dumps({
                    "status": "human_action_required",
                    "reason": login.reason,
                }, sort_keys=True))
                return 4

            if not login.authenticated:
                if portal == "naukri":
                    # Only re-use a verified local session. Google rejects
                    # sign-in from some automated browsers; offer a human-
                    # controlled Naukri OTP setup, never Google password reuse.
                    print(json.dumps({
                        "status": "naukri_session_required",
                        "portal": "naukri",
                        "reason": login.reason,
                        "setup_command": "python src/naukri_google_setup.py --method otp",
                    }, sort_keys=True))
                    return 4
                if portal == "linkedin" and not policy.sign_in_if_needed:
                    print(json.dumps({
                        "status": "login_required",
                        "reason": login.reason,
                    }, sort_keys=True))
                    return 4
                if portal == "linkedin":
                    try:
                        local = load_portal_credentials(args.credentials_file, "linkedin")
                    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
                        print(json.dumps({
                            "status": "login_required",
                            "reason": str(exc),
                        }, sort_keys=True))
                        return 4
                    with trace_step("linkedin_sign_in"):
                        auth = execute_linkedin_sign_in(
                            page,
                            BrowserAuthCredentials(local.email, local.password),
                        )
                    if not auth.authenticated:
                        print(json.dumps({
                            "status": auth.state,
                            "reason": auth.reason,
                            "action": auth.action,
                        }, sort_keys=True))
                        return 4

            if exact_target is not None:
                # Do not open job search or fall back to other listings.
                try:
                    with trace_step("exact_job_inspection", job_id=exact_target.job_id):
                        selected_job = inspect_exact_linkedin_job(
                            page, exact_target, public_profile.skill_taxonomy
                        )
                except ValueError as exc:
                    reason = str(exc)
                    if (getattr(args, "public_job_url", "") and
                            reason.startswith(("exact_job_metadata_unverified:", "exact_job_description_missing_or_short"))):
                        try:
                            selected_job = fetch_public_exact_linkedin_job(
                                args.public_job_url, exact_target, public_profile.skill_taxonomy
                            )
                            trace_event("exact_job_public_metadata_verified",
                                        job_id=exact_target.job_id,
                                        description_length=len(selected_job.description),
                                        required_skills_count=len(selected_job.required_skills))
                        except ValueError as fetch_error:
                            reason += "|public_fallback:" + str(fetch_error)
                            selected_job = None
                    else:
                        selected_job = None
                    if selected_job is None:
                        print(json.dumps({
                            "status": "exact_job_inspection_blocked", "reason": reason,
                            "job_id": exact_target.job_id, "attempted": 0, "confirmed": 0,
                        }, sort_keys=True))
                        return 4
                jobs = [selected_job]
                trace_event("exact_job_selected", job_id=exact_target.job_id,
                            job_count=1, jd_length=len(selected_job.description),
                            jd_skills=len(selected_job.required_skills))
            else:
                with trace_step(f"{portal}_search_navigation", query=args.query, location=args.location):
                    adapter.open_search(args.query, args.location)

                try:
                    search_body = page.locator("body").inner_text(timeout=5000)
                except Exception:
                    search_body = ""
                search_probe = classify_linkedin_probe if portal == 'linkedin' else classify_naukri_probe
                search_state = search_probe(
                    str(getattr(page, "url", "") or ""),
                    search_body,
                )
                if search_state.needs_human_action or not search_state.authenticated:
                    print(json.dumps({
                        "status": "search_session_not_authenticated",
                        "reason": search_state.reason,
                    }, sort_keys=True))
                    return 4

                with trace_step("search_result_extraction"):
                    jobs = adapter.extract_search_results(public_profile.skill_taxonomy)
                    jobs = jobs[: max(args.max_jobs, 0)]
                trace_event("search_results_ready", job_count=len(jobs))

            def enrich(job):
                if exact_target is not None:
                    # The selected job was already inspected from its canonical
                    # detail page. Preserve that exact JD and job identity.
                    if job.external_id != exact_target.job_id or job.url != exact_target.url:
                        raise ValueError("exact_job_changed_before_enrichment")
                    return EnrichmentResult(job=job, enriched=True)
                trace_event(
                    "jd_read_start",
                    job_key=job.key,
                    company=job.company,
                    title=job.title,
                )
                result = enrich_job_with_page(
                    page,
                    job,
                    public_profile.skill_taxonomy,
                )
                trace_event(
                    "jd_read_result",
                    job_key=job.key,
                    enriched=result.enriched,
                    reason=result.reason,
                    description_length=len(result.job.description or ""),
                    required_skills=list(result.job.required_skills),
                    minimum_years=result.job.minimum_years,
                )
                return result

            def apply_job(job, profile):
                trace_event(
                    "application_open_start",
                    job_key=job.key,
                    company=job.company,
                    title=job.title,
                )
                if portal != "linkedin":
                    # Discovery/scoring is supported independently. Do not
                    # pretend LinkedIn-specific application entry works on Naukri.
                    trace_event(
                        "portal_application_unsupported",
                        portal=portal,
                        job_key=job.key,
                        reason="naukri_submission_adapter_not_verified",
                    )
                    return ApplicationAttempt(
                        state="BLOCKED",
                        reason="naukri_submission_adapter_not_verified",
                    )
                bounded_goto(page, job.url)
                if exact_target is not None:
                    ensure_exact_target(page, exact_target)
                try:
                    run = run_linkedin_application(
                        page,
                        dict(profile),
                        open_easy_apply=True,
                        open_external_apply=True,
                        fill_application=True,
                        advance_application=True,
                        inspect_review=True,
                        submit_application=True,
                        live_submission_enabled=True,
                        resume_path=args.resume_path,
                        external_account_credentials=external_credentials,
                        create_account_if_missing=policy.create_account_if_missing,
                    )
                except Exception as exc:
                    # An application may already have changed on-screen
                    # before an exception. Capture first; never retry it.
                    capture_blocker(
                        page, stage="live_application_exception",
                        outcome="EXCEPTION",
                        reason_code=type(exc).__name__,
                    )
                    hold_blocked_browser(page, getattr(args, "debug_hold_seconds", 0))
                    raise

                if not (run.submission is not None and run.submission.confirmed):
                    flow = run.flow
                    capture_blocker(
                        page, stage="live_application_unconfirmed",
                        outcome=(flow.state if flow is not None else run.engine_stage),
                        reason_code=(
                            flow.reasons[0] if flow is not None and flow.reasons
                            else run.entry.reason or run.entry.application_state
                        ),
                        steps_completed=(flow.steps_completed if flow is not None else 0),
                    )
                    hold_blocked_browser(page, getattr(args, "debug_hold_seconds", 0))

                trace_event(
                    "end_to_end_application_result",
                    job_key=job.key,
                    engine_stage=run.engine_stage,
                    engine_history=list(run.engine_history),
                    entry_state=run.entry.application_state,
                    application_type=run.entry.application_type,
                    ats_provider=run.entry.ats_provider,
                    flow_state=run.flow.state if run.flow is not None else "",
                    submission_state=run.submission.state if run.submission is not None else "",
                    confirmed=bool(run.submission and run.submission.confirmed),
                    reason=_application_reason(run),
                )

                if run.submission is not None and run.submission.confirmed:
                    return ApplicationAttempt(
                        state="CONFIRMED",
                        confirmed=True,
                        submission=run.submission,
                    )
                return ApplicationAttempt(
                    state=run.engine_stage or "BLOCKED",
                    confirmed=False,
                    reason=_application_reason(run),
                    submission=run.submission,
                )

            with trace_step("application_batch", job_count=len(jobs)):
                summary = run_application_batch(
                    jobs,
                    profile=public_profile,
                    private_profile=private_profile,
                    policy=policy,
                    store=store,
                    enrich_job=enrich,
                    apply_job=apply_job,
                    allow_outside_window=testing_mode or args.allow_outside_window,
                    max_application_attempts=1,
                )

            report = asdict(summary)
            job_counts = _pilot_job_counts(len(jobs), summary.discovered)
            report["discovered"] = job_counts["discovered"]
            report["considered"] = job_counts["considered"]
            # An exhausted pilot cap is NOT application success. Only a
            # positively recorded submission may return exit code 0.
            pilot_result, pilot_exit_code = _pilot_result(summary.confirmed)
            db_verified = False
            db_recorded_at = ""
            if exact_target is not None and summary.confirmed == 1:
                ledger = store.get_confirmed_submission(
                    "linkedin", exact_target.job_id
                )
                db_verified = bool(ledger)
                db_recorded_at = ledger["applied_at"] if ledger else ""
                trace_event(
                    "exact_job_confirmation_ledger_readback",
                    job_id=exact_target.job_id,
                    verified=db_verified,
                )
                if not db_verified:
                    # Even if the portal click appeared successful, a missing
                    # local ledger record is NOT a completed agent pilot.
                    pilot_result, pilot_exit_code = "pilot_ledger_unverified", 5
            report["pilot_result"] = pilot_result
            report["db_verified"] = db_verified
            report["db_recorded_at"] = db_recorded_at
            active_trace = get_active_tracer()
            report["run_id"] = active_trace.run_id if active_trace is not None else ""
            report["trace_file"] = str(active_trace.events_path) if active_trace is not None else ""
            report["submission_enabled"] = True
            report["execution_mode"] = "testing" if testing_mode else "production"

            target = Path(args.report)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2), encoding="utf-8")

            print(json.dumps({
                "status": pilot_result,
                "batch_status": summary.status,
                **job_counts,
                "qualified": summary.qualified,
                "attempted": summary.attempted,
                "confirmed": summary.confirmed,
                "blocked": summary.blocked,
                "report": str(target),
                "run_id": report["run_id"],
                "trace_file": report["trace_file"],
                "submission_enabled": True,
                "db_verified": db_verified,
                "db_recorded_at": db_recorded_at,
                "execution_mode": "testing" if testing_mode else "production",
            }, sort_keys=True))
            return pilot_exit_code

    except BrowserRuntimeUnavailable as exc:
        print(json.dumps({
            "status": "browser_runtime_unavailable",
            "reason": str(exc),
        }, sort_keys=True))
        return 2


def main() -> int:
    args = parse_args()
    tracer = RunTracer(
        args.trace_dir,
        heartbeat_seconds=args.heartbeat_seconds,
        print_events=True,
    )
    token = set_active_tracer(tracer)
    tracer.start()
    try:
        exit_code = _run(args)
        tracer.finish(
            "completed" if exit_code == 0 else "failed",
            exit_code=exit_code,
        )
        return exit_code
    except KeyboardInterrupt:
        tracer.finish("interrupted", exit_code=130)
        print(json.dumps({
            "status": "interrupted",
            "run_id": tracer.run_id,
            "trace": str(tracer.events_path),
        }, sort_keys=True))
        return 130
    except Exception as exc:
        trace_event(
            "unhandled_exception",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        tracer.finish("failed", exit_code=1)
        raise
    finally:
        reset_active_tracer(token)


if __name__ == "__main__":
    raise SystemExit(main())
