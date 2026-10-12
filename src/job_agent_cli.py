import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from agent_trace import RunTracer, get_active_tracer, reset_active_tracer, set_active_tracer, trace_event, trace_step
from application_runner import ApplicationAttempt, run_application_batch
from automation_policy import load_automation_policy
from browser_auth import BrowserAuthCredentials, execute_linkedin_sign_in
from browser_portals import LinkedInBrowserAdapter, classify_linkedin_probe
from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession
from jd_enrichment import enrich_job_with_page
from linkedin_application import run_linkedin_application
from local_credentials import load_first_portal_credentials, load_portal_credentials
from models import CandidateProfile
from navigation import bounded_goto
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
        help="Full path to the resume file. Defaults to JOB_AGENT_RESUME_PATH.",
    )
    parser.add_argument("--query", default="Customer Success Manager")
    parser.add_argument("--location", default="India")
    parser.add_argument("--max-jobs", type=int, default=20)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--trace-dir", default="data/agent_runs")
    parser.add_argument("--heartbeat-seconds", type=float, default=5.0)
    parser.add_argument(
        "--allow-outside-window",
        action="store_true",
        help="Controlled QA only. Production schedule should omit this flag.",
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


def _run(args: argparse.Namespace) -> int:
    trace_event("configuration_load_start")
    public_profile = CandidateProfile.from_dict(_load_json(args.profile))
    private_profile = _load_json(args.private_profile)
    policy = load_automation_policy(args.policy)
    store = JobStore(args.db)

    if not policy.live_submission_enabled:
        print(json.dumps({
            "status": "live_submission_disabled",
            "policy": args.policy,
        }, sort_keys=True))
        return 3

    raw_resume_path = str(args.resume_path or "").strip()
    if not raw_resume_path:
        print(json.dumps({
            "status": "resume_path_required",
            "reason": "Set JOB_AGENT_RESUME_PATH or pass --resume-path with the full path to a PDF/DOC/DOCX resume file.",
        }, sort_keys=True))
        return 2

    resume = Path(raw_resume_path).expanduser()
    if not resume.exists() or not resume.is_file():
        print(json.dumps({
            "status": "invalid_resume_path",
            "resume_path": str(resume),
            "reason": "Resume path must point to an existing file, not a directory.",
        }, sort_keys=True))
        return 2
    args.resume_path = str(resume.resolve())

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
            adapter = LinkedInBrowserAdapter(page)

            with trace_step("linkedin_session_check"):
                login = adapter.login_state()
            trace_event(
                "linkedin_session_state",
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
                if not policy.sign_in_if_needed:
                    print(json.dumps({
                        "status": "login_required",
                        "reason": login.reason,
                    }, sort_keys=True))
                    return 4
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

            with trace_step("linkedin_search_navigation", query=args.query, location=args.location):
                adapter.open_search(args.query, args.location)

            try:
                search_body = page.locator("body").inner_text(timeout=5000)
            except Exception:
                search_body = ""
            search_state = classify_linkedin_probe(
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
                bounded_goto(page, job.url)
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
                    allow_outside_window=args.allow_outside_window,
                )

            report = asdict(summary)
            active_trace = get_active_tracer()
            report["run_id"] = active_trace.run_id if active_trace is not None else ""
            report["trace_file"] = str(active_trace.events_path) if active_trace is not None else ""
            report["submission_enabled"] = True

            target = Path(args.report)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2), encoding="utf-8")

            print(json.dumps({
                "status": summary.status,
                "discovered": summary.discovered,
                "qualified": summary.qualified,
                "attempted": summary.attempted,
                "confirmed": summary.confirmed,
                "blocked": summary.blocked,
                "report": str(target),
                "run_id": report["run_id"],
                "trace_file": report["trace_file"],
                "submission_enabled": True,
            }, sort_keys=True))
            return 0

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
