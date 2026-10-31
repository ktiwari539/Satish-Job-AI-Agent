import argparse
import json
from dataclasses import asdict
from pathlib import Path

from agent_trace import RunTracer, get_active_tracer, reset_active_tracer, set_active_tracer, trace_event, trace_step
from automation_policy import load_automation_policy
from browser_auth import BrowserAuthCredentials, execute_linkedin_sign_in
from browser_portals import LinkedInBrowserAdapter, classify_linkedin_probe
from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession
from jd_enrichment import enrich_job_with_page
from linkedin_application import run_linkedin_application
from local_credentials import load_portal_credentials
from models import CandidateProfile
from navigation import bounded_goto
from review_runner import ReviewPreparationResult, prepare_review_batch
from store import JobStore


def _load_json(path: str) -> dict:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(path)
    return json.loads(target.read_text(encoding="utf-8"))


def _prepare_linkedin(page, private_profile: dict, resume_path: str):
    def prepare(job, profile):
        trace_event(
            "application_open_start",
            job_key=job.key,
            company=job.company,
            title=job.title,
            job_id=job.external_id,
        )
        with trace_step("application_job_page", job_key=job.key, job_url=job.url):
            bounded_goto(page, job.url)

        with trace_step("linkedin_application_flow", job_key=job.key):
            run = run_linkedin_application(
                page,
                dict(profile),
                open_easy_apply=True,
                open_external_apply=True,
                fill_application=True,
                advance_application=True,
                inspect_review=True,
                submit_application=False,
                live_submission_enabled=False,
                resume_path=resume_path,
            )

        trace_event(
            "application_entry_result",
            job_key=job.key,
            application_type=run.entry.application_type,
            application_state=run.entry.application_state,
            ats_provider=run.entry.ats_provider,
            opened=run.entry.opened,
            field_count=run.entry.field_count,
            required_field_count=run.entry.required_field_count,
            reason=run.entry.reason,
            diagnostic_actions=list(run.entry.diagnostic_actions),
            current_url=run.entry.url,
        )
        trace_event(
            "application_engine_result",
            job_key=job.key,
            engine_stage=run.engine_stage,
            engine_history=list(run.engine_history),
        )

        flow = run.flow
        if flow is None:
            entry_reason = run.entry.reason or run.entry.application_state
            return ReviewPreparationResult(
                state="BLOCKED",
                reason=(
                    f"{run.entry.application_type}:"
                    f"{run.entry.application_state}:"
                    f"{entry_reason}"
                ),
            )

        trace_event(
            "application_flow_result",
            job_key=job.key,
            flow_state=flow.state,
            steps_completed=flow.steps_completed,
            reasons=list(flow.reasons),
            unknown_required_count=len(flow.unknown_required_fields),
            missing_profile_value_count=len(flow.missing_profile_values),
            actions=list(flow.actions),
            review_checks=list(flow.review_checks),
            review_mismatches=list(flow.review_mismatches),
            visible_actions=list(flow.visible_actions),
            current_url=flow.current_url,
        )

        if flow.state == "REVIEW_INSPECTED" and not flow.review_mismatches:
            return ReviewPreparationResult("READY_FOR_REVIEW")

        if flow.state == "SUBMIT_READY":
            return ReviewPreparationResult(
                "READY_FOR_REVIEW",
                "direct_submit_control_requires_user_review",
            )

        reason_parts = [flow.state]
        reason_parts.extend(flow.reasons)
        reason_parts.extend(flow.review_mismatches)
        return ReviewPreparationResult(
            state="BLOCKED",
            reason="|".join(part for part in reason_parts if part),
        )

    return prepare


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare qualified LinkedIn applications up to the final review step."
    )
    parser.add_argument("--profile", default="config/qa_profile.json")
    parser.add_argument("--private-profile", default="data/private_profile.json")
    parser.add_argument("--policy", default="config/automation_policy.example.json")
    parser.add_argument("--credentials-file", default="data/portal_credentials.json")
    parser.add_argument("--profile-dir", default="browser-profile")
    parser.add_argument("--db", default="data/jobs.db")
    parser.add_argument("--report", default="data/review_ready_report.json")
    parser.add_argument("--resume-path", required=True)
    parser.add_argument("--query", default="Customer Success Manager")
    parser.add_argument("--location", default="India")
    parser.add_argument("--max-jobs", type=int, default=20)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--trace-dir", default="data/agent_runs")
    parser.add_argument("--heartbeat-seconds", type=float, default=5.0)
    parser.add_argument(
        "--allow-outside-window",
        action="store_true",
        help="Manual QA only. Production preparation should respect configured windows.",
    )
    return parser.parse_args()


def _run(args: argparse.Namespace) -> int:
    trace_event("configuration_load_start")
    public_profile = CandidateProfile.from_dict(_load_json(args.profile))
    private_profile = _load_json(args.private_profile)
    policy = load_automation_policy(args.policy)
    store = JobStore(args.db)
    trace_event(
        "configuration_loaded",
        threshold=policy.threshold,
        duplicate_cooldown_days=policy.duplicate_cooldown_days,
        query=args.query,
        location=args.location,
        max_jobs=args.max_jobs,
        headless=args.headless,
    )

    resume = Path(args.resume_path).expanduser()
    if not resume.exists() or not resume.is_file():
        trace_event("configuration_error", reason="invalid_resume_path", resume_path=str(resume))
        print(json.dumps({
            "status": "invalid_resume_path",
            "resume_path": str(resume),
        }, sort_keys=True))
        return 2
    args.resume_path = str(resume.resolve())
    trace_event("resume_validated", resume_path=args.resume_path, resume_size_bytes=resume.stat().st_size)

    if not args.allow_outside_window and policy.active_window() is None:
        trace_event("policy_block", reason="outside_application_window")
        print(json.dumps({
            "status": "outside_application_window",
            "ready_for_review": 0,
        }, sort_keys=True))
        return 3

    runtime_config = BrowserRuntimeConfig(
        user_data_dir=args.profile_dir,
        headless=args.headless,
        slow_mo_ms=125,
    )

    try:
        trace_event("browser_start", profile_dir=args.profile_dir, headless=args.headless)
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
                    trace_event("login_blocked", reason=str(exc))
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
                trace_event(
                    "linkedin_sign_in_result",
                    authenticated=auth.authenticated,
                    state=auth.state,
                    action=auth.action,
                    reason=auth.reason,
                    current_url=auth.current_url,
                )
                if not auth.authenticated:
                    print(json.dumps({
                        "status": auth.state,
                        "reason": auth.reason,
                        "action": auth.action,
                    }, sort_keys=True))
                    return 4

            try:
                with trace_step("linkedin_search_navigation", query=args.query, location=args.location):
                    adapter.open_search(args.query, args.location)
            except Exception as exc:
                trace_event(
                    "search_navigation_failed",
                    error_type=type(exc).__name__,
                    current_url=str(getattr(page, "url", "") or ""),
                )
                print(json.dumps({
                    "status": "search_navigation_failed",
                    "reason": type(exc).__name__,
                    "current_url": str(getattr(page, "url", "") or ""),
                }, sort_keys=True))
                return 5

            try:
                search_body = page.locator("body").inner_text(timeout=5000)
            except Exception:
                search_body = ""
            search_state = classify_linkedin_probe(
                str(getattr(page, "url", "") or ""),
                search_body,
            )
            trace_event(
                "search_session_state",
                authenticated=search_state.authenticated,
                needs_human_action=search_state.needs_human_action,
                reason=search_state.reason,
                current_url=str(getattr(page, "url", "") or ""),
            )
            if search_state.needs_human_action:
                print(json.dumps({
                    "status": "human_action_required",
                    "reason": search_state.reason,
                }, sort_keys=True))
                return 4
            if not search_state.authenticated:
                print(json.dumps({
                    "status": "search_session_not_authenticated",
                    "reason": search_state.reason,
                }, sort_keys=True))
                return 4

            with trace_step("search_result_extraction"):
                jobs = adapter.extract_search_results(public_profile.skill_taxonomy)
                jobs = jobs[: max(args.max_jobs, 0)]
            trace_event("search_results_ready", job_count=len(jobs))

            def enrich_with_progress(job):
                trace_event(
                    "jd_read_start",
                    job_key=job.key,
                    company=job.company,
                    title=job.title,
                    job_id=job.external_id,
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
                    remote=result.job.remote,
                )
                return result

            with trace_step("review_batch", job_count=len(jobs)):
                summary = prepare_review_batch(
                    jobs,
                    profile=public_profile,
                    private_profile=private_profile,
                    threshold=policy.threshold,
                    cooldown_days=policy.duplicate_cooldown_days,
                    store=store,
                    enrich_job=enrich_with_progress,
                    prepare_job=_prepare_linkedin(page, private_profile, args.resume_path),
                )

            report = asdict(summary)
            report["status"] = "completed"
            report["portal"] = "linkedin"
            report["query"] = args.query
            report["location"] = args.location
            report["submission_performed"] = False
            active_trace = get_active_tracer()
            report["run_id"] = active_trace.run_id if active_trace is not None else ""
            report["trace_file"] = (
                str(active_trace.events_path) if active_trace is not None else ""
            )

            target = Path(args.report)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2), encoding="utf-8")

            trace_event(
                "review_batch_complete",
                discovered=summary.discovered,
                qualified=summary.qualified,
                ready_for_review=summary.ready_for_review,
                blocked=summary.blocked,
                skipped_duplicate=summary.skipped_duplicate,
                skipped_unqualified=summary.skipped_unqualified,
                skipped_ineligible=summary.skipped_ineligible,
                skipped_jd=summary.skipped_jd,
                report=str(target),
            )
            print(json.dumps({
                "status": "completed",
                "discovered": summary.discovered,
                "qualified": summary.qualified,
                "ready_for_review": summary.ready_for_review,
                "blocked": summary.blocked,
                "report": str(target),
                "run_id": report["run_id"],
                "trace_file": report["trace_file"],
                "diagnostics_command": "python src/agent_status.py",
                "submission_performed": False,
            }, sort_keys=True))
            return 0

    except BrowserRuntimeUnavailable as exc:
        trace_event("browser_runtime_unavailable", reason=str(exc))
        print(json.dumps({
            "status": "browser_runtime_unavailable",
            "reason": str(exc),
        }, sort_keys=True))
        return 2
    finally:
        trace_event("browser_stop")


def main() -> int:
    args = parse_args()
    tracer = RunTracer(
        args.trace_dir,
        heartbeat_seconds=args.heartbeat_seconds,
        print_events=True,
    )
    token = set_active_tracer(tracer)
    tracer.start()
    exit_code = 1
    try:
        exit_code = _run(args)
        tracer.finish(
            "completed" if exit_code == 0 else "failed",
            exit_code=exit_code,
        )
        return exit_code
    except KeyboardInterrupt:
        exit_code = 130
        tracer.finish("interrupted", exit_code=exit_code)
        print(json.dumps({
            "status": "interrupted",
            "run_id": tracer.run_id,
            "trace": str(tracer.events_path),
        }, sort_keys=True))
        return exit_code
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
