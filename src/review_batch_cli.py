import argparse
import json
from dataclasses import asdict
from pathlib import Path

from automation_policy import load_automation_policy
from browser_auth import BrowserAuthCredentials, execute_linkedin_sign_in
from browser_portals import LinkedInBrowserAdapter, classify_linkedin_probe
from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession
from jd_enrichment import enrich_job_with_page
from linkedin_application import run_linkedin_application
from local_credentials import load_portal_credentials
from models import CandidateProfile
from review_runner import ReviewPreparationResult, prepare_review_batch
from store import JobStore


def _load_json(path: str) -> dict:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(path)
    return json.loads(target.read_text(encoding="utf-8"))


def _prepare_linkedin(page, private_profile: dict, resume_path: str):
    def prepare(job, profile):
        page.goto(job.url, wait_until="domcontentloaded")
        run = run_linkedin_application(
            page,
            dict(profile),
            open_easy_apply=True,
            open_external_apply=False,
            fill_application=True,
            advance_application=True,
            inspect_review=True,
            submit_application=False,
            live_submission_enabled=False,
            resume_path=resume_path,
        )

        flow = run.flow
        if flow is None:
            return ReviewPreparationResult(
                state="BLOCKED",
                reason=run.entry.reason or run.entry.application_state,
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
    parser.add_argument(
        "--allow-outside-window",
        action="store_true",
        help="Manual QA only. Production preparation should respect configured windows.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    public_profile = CandidateProfile.from_dict(_load_json(args.profile))
    private_profile = _load_json(args.private_profile)
    policy = load_automation_policy(args.policy)
    store = JobStore(args.db)

    resume = Path(args.resume_path).expanduser()
    if not resume.exists() or not resume.is_file():
        print(json.dumps({
            "status": "invalid_resume_path",
            "resume_path": str(resume),
        }, sort_keys=True))
        return 2
    args.resume_path = str(resume.resolve())

    if not args.allow_outside_window and policy.active_window() is None:
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
        with PlaywrightSession(runtime_config) as runtime:
            page = runtime.page
            adapter = LinkedInBrowserAdapter(page)
            login = adapter.login_state()

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

            try:
                adapter.open_search(args.query, args.location)
            except Exception as exc:
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

            jobs = adapter.extract_search_results(public_profile.skill_taxonomy)
            jobs = jobs[: max(args.max_jobs, 0)]

            summary = prepare_review_batch(
                jobs,
                profile=public_profile,
                private_profile=private_profile,
                threshold=policy.threshold,
                cooldown_days=policy.duplicate_cooldown_days,
                store=store,
                enrich_job=lambda job: enrich_job_with_page(
                    page,
                    job,
                    public_profile.skill_taxonomy,
                ),
                prepare_job=_prepare_linkedin(page, private_profile, args.resume_path),
            )

            report = asdict(summary)
            report["status"] = "completed"
            report["portal"] = "linkedin"
            report["query"] = args.query
            report["location"] = args.location
            report["submission_performed"] = False

            target = Path(args.report)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2), encoding="utf-8")

            print(json.dumps({
                "status": "completed",
                "discovered": summary.discovered,
                "qualified": summary.qualified,
                "ready_for_review": summary.ready_for_review,
                "blocked": summary.blocked,
                "report": str(target),
                "submission_performed": False,
            }, sort_keys=True))
            return 0

    except BrowserRuntimeUnavailable as exc:
        print(json.dumps({
            "status": "browser_runtime_unavailable",
            "reason": str(exc),
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
