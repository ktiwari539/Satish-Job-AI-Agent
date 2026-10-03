import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession
from matcher import score_profile
from models import CandidateProfile
from policy import evaluate_eligibility
from browser_portals import (
    NaukriBrowserAdapter,
    LinkedInBrowserAdapter,
    classify_linkedin_probe,
    classify_naukri_probe,
)
from jd_enrichment import enrich_job_with_page
from portal_catalog import PORTAL_TARGETS, build_search_url
from apply_inspection import inspect_linkedin_application_entry
from application_flow import run_safe_application_flow
from store import JobStore


AUTH_PORTALS = (
    "linkedin",
    "naukri",
    "indeed",
    "foundit",
    "instahyre",
    "cutshort",
    "wellfound",
    "hirist",
    "glassdoor",
)


@dataclass(frozen=True)
class PortalQAResult:
    portal: str
    status: str
    reason: str = ""
    url: str = ""
    checked_at: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_generic_session(portal: str, url: str, body_text: str) -> PortalQAResult:
    u = url.lower()
    text = " ".join(body_text.lower().split())

    challenge_markers = (
        "captcha",
        "verify you are human",
        "security check",
        "unusual traffic",
        "access denied",
    )
    if any(marker in text for marker in challenge_markers):
        return PortalQAResult(portal, "HUMAN_ACTION_REQUIRED", "security_or_captcha_challenge", url, utc_now())

    login_url_markers = ("/login", "/signin", "/sign-in", "/account/login")
    login_text_markers = (
        "sign in",
        "log in",
        "login",
        "email address",
        "password",
    )
    if any(marker in u for marker in login_url_markers):
        return PortalQAResult(portal, "LOGIN_REQUIRED", "login_page_detected", url, utc_now())

    logout_markers = (
        "logout",
        "log out",
        "my profile",
        "view profile",
        "my account",
        "account settings",
    )
    if any(marker in text for marker in logout_markers):
        return PortalQAResult(portal, "SESSION_CONFIRMED", "", url, utc_now())

    if sum(marker in text for marker in login_text_markers) >= 2:
        return PortalQAResult(portal, "LOGIN_REQUIRED", "login_markers_detected", url, utc_now())

    return PortalQAResult(portal, "SESSION_UNVERIFIED", "portal_specific_probe_not_yet_validated", url, utc_now())


def inspect_portal_session(page, portal: str) -> PortalQAResult:
    target = PORTAL_TARGETS[portal]
    page.goto(target.start_url, wait_until="domcontentloaded")

    if portal == "linkedin":
        try:
            body = page.locator("body").inner_text(timeout=5000)
        except Exception:
            body = ""
        state = classify_linkedin_probe(page.url, body)
        return PortalQAResult(
            portal,
            "SESSION_CONFIRMED" if state.authenticated else (
                "HUMAN_ACTION_REQUIRED" if state.needs_human_action else "LOGIN_REQUIRED"
            ),
            state.reason,
            page.url,
            utc_now(),
        )

    if portal == "naukri":
        try:
            body = page.locator("body").inner_text(timeout=5000)
        except Exception:
            body = ""
        state = classify_naukri_probe(page.url, body)
        return PortalQAResult(
            portal,
            "SESSION_CONFIRMED" if state.authenticated else (
                "HUMAN_ACTION_REQUIRED" if state.needs_human_action else "LOGIN_REQUIRED"
            ),
            state.reason,
            page.url,
            utc_now(),
        )

    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        body = ""
    return classify_generic_session(portal, page.url, body)


def save_status(path: str, result: PortalQAResult) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    else:
        payload = {}
    payload[result.portal] = asdict(result)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def run_login_validation(page, portal: str, status_file: str, interactive: bool) -> PortalQAResult:
    result = inspect_portal_session(page, portal)
    if result.status in {"LOGIN_REQUIRED", "SESSION_UNVERIFIED"} and interactive:
        print(f"[{portal}] Browser opened at: {page.url}")
        print("Log in directly in the browser. Complete any OTP/CAPTCHA/MFA yourself.")
        input("Press Enter here after the portal is fully logged in... ")
        result = inspect_portal_session(page, portal)

    save_status(status_file, result)
    return result


def extract_current_jobs(page, portal: str, taxonomy: tuple[str, ...]):
    if portal == "linkedin":
        return LinkedInBrowserAdapter(page).extract_search_results(taxonomy)
    if portal == "naukri":
        return NaukriBrowserAdapter(page).extract_search_results(taxonomy)
    return []


def run_search_probe(page, portal: str, query: str, location: str) -> PortalQAResult:
    url = build_search_url(portal, query, location)
    page.goto(url, wait_until="domcontentloaded")
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        body = ""

    if any(x in body.lower() for x in ("captcha", "verify you are human", "security check")):
        return PortalQAResult(portal, "HUMAN_ACTION_REQUIRED", "search_challenge", page.url, utc_now())

    if portal == "linkedin":
        adapter = LinkedInBrowserAdapter(page)
        jobs = adapter.extract_search_results(())
        return PortalQAResult(
            portal,
            "SEARCH_RESULTS_FOUND" if jobs else "SEARCH_RESULT_SELECTORS_UNVERIFIED",
            f"result_count={len(jobs)}",
            page.url,
            utc_now(),
        )

    if portal == "naukri":
        adapter = NaukriBrowserAdapter(page)
        jobs = adapter.extract_search_results(())
        return PortalQAResult(
            portal,
            "SEARCH_RESULTS_FOUND" if jobs else "SEARCH_RESULT_SELECTORS_UNVERIFIED",
            f"result_count={len(jobs)}",
            page.url,
            utc_now(),
        )

    return PortalQAResult(portal, "SEARCH_PAGE_OPENED", "portal_specific_result_extractor_pending", page.url, utc_now())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local real-session QA runner. Never submits applications.")
    parser.add_argument("--portal", default="linkedin", choices=(*AUTH_PORTALS, "all"))
    parser.add_argument("--profile-dir", default="browser-profile")
    parser.add_argument("--status-file", default="data/browser_qa_status.json")
    parser.add_argument("--db", default="data/jobs.db")
    parser.add_argument("--job-report-file", default="data/browser_qa_jobs.json")
    parser.add_argument("--job-url", default="")
    parser.add_argument("--profile", default="config/qa_profile.json")
    parser.add_argument("--max-jobs", type=int, default=3)
    parser.add_argument("--login-only", action="store_true")
    parser.add_argument("--search-only", action="store_true")
    parser.add_argument("--inspect-jds", action="store_true")
    parser.add_argument("--inspect-apply", action="store_true")
    parser.add_argument("--open-easy-apply", action="store_true")
    parser.add_argument("--open-external-apply", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--fill-application", action="store_true")
    parser.add_argument("--advance-application", action="store_true")
    parser.add_argument("--private-profile", default="data/private_profile.json")
    parser.add_argument("--resume-path", default="")
    parser.add_argument("--query", default="Customer Success Manager")
    parser.add_argument("--location", default="India")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    portals = AUTH_PORTALS if args.portal == "all" else (args.portal,)
    store = JobStore(args.db)
    config = BrowserRuntimeConfig(
        user_data_dir=args.profile_dir,
        headless=args.headless,
        slow_mo_ms=125,
    )

    try:
        with PlaywrightSession(config) as runtime:
            page = runtime.page
            for portal in portals:
                print(f"\n=== {portal.upper()} ===")
                login = run_login_validation(
                    page,
                    portal,
                    args.status_file,
                    interactive=not args.non_interactive,
                )
                print(json.dumps(asdict(login), indent=2))

                if args.login_only:
                    continue
                if login.status != "SESSION_CONFIRMED":
                    print("Skipping search probe until session is confirmed.")
                    continue

                if args.job_url:
                    if store.is_applied_url(args.job_url):
                        print(json.dumps({
                            "portal": portal,
                            "job_url": args.job_url,
                            "application_state": "SKIPPED_ALREADY_APPLIED",
                        }, indent=2))
                        continue
                    page.goto(args.job_url, wait_until="domcontentloaded")
                    direct_inspection = inspect_linkedin_application_entry(
                        page,
                        open_easy_apply=args.open_easy_apply,
                        open_external_apply=args.open_external_apply,
                    )
                    direct_flow = None
                    if (
                        args.fill_application
                        and direct_inspection.application_state == "FORM_READY"
                    ):
                        private_profile_path = Path(args.private_profile)
                        if not private_profile_path.exists():
                            raise FileNotFoundError(
                                f"Private application profile not found: {private_profile_path}"
                            )
                        private_profile = json.loads(
                            private_profile_path.read_text(encoding="utf-8")
                        )
                        direct_flow = run_safe_application_flow(
                            page,
                            private_profile,
                            resume_path=args.resume_path,
                            advance=args.advance_application,
                        )
                    direct_report = {
                        "portal": portal,
                        "job_url": args.job_url,
                        "application_entry": asdict(direct_inspection),
                        "application_flow": (
                            asdict(direct_flow) if direct_flow is not None else None
                        ),
                    }
                    report_path = Path(args.job_report_file)
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(
                        json.dumps([direct_report], indent=2),
                        encoding="utf-8",
                    )
                    print(json.dumps(direct_report, indent=2))
                    continue

                search = run_search_probe(page, portal, args.query, args.location)
                save_status(args.status_file, search)
                print(json.dumps(asdict(search), indent=2))

                if args.search_only:
                    continue

                if args.inspect_jds:
                    profile_data = json.loads(Path(args.profile).read_text(encoding="utf-8"))
                    profile = CandidateProfile.from_dict(profile_data)
                    jobs = extract_current_jobs(page, portal, profile.skill_taxonomy)
                    report = []
                    for job in jobs[: max(args.max_jobs, 0)]:
                        enrichment = enrich_job_with_page(page, job, profile.skill_taxonomy)
                        scored_job = enrichment.job
                        match = score_profile(profile, scored_job)
                        eligibility = evaluate_eligibility(profile, scored_job)
                        apply_inspection = None
                        already_applied = store.is_applied(scored_job)
                        if (
                            not already_applied
                            and args.inspect_apply
                            and portal == "linkedin"
                            and enrichment.enriched
                            and eligibility.eligible
                            and match.decision == "APPLY"
                        ):
                            apply_inspection = inspect_linkedin_application_entry(
                                page,
                                open_easy_apply=args.open_easy_apply,
                                open_external_apply=args.open_external_apply,
                            )

                        application_flow = None
                        if (
                            apply_inspection is not None
                            and args.fill_application
                            and apply_inspection.application_state == "FORM_READY"
                        ):
                            private_profile_path = Path(args.private_profile)
                            if not private_profile_path.exists():
                                raise FileNotFoundError(
                                    f"Private application profile not found: {private_profile_path}"
                                )
                            private_profile = json.loads(
                                private_profile_path.read_text(encoding="utf-8")
                            )
                            application_flow = run_safe_application_flow(
                                page,
                                private_profile,
                                resume_path=args.resume_path,
                                advance=args.advance_application,
                            )

                        report.append(
                            {
                                "portal": portal,
                                "title": scored_job.title,
                                "company": scored_job.company,
                                "location": scored_job.location,
                                "url": scored_job.url,
                                "jd_enriched": enrichment.enriched,
                                "jd_reason": enrichment.reason,
                                "required_skills": list(scored_job.required_skills),
                                "minimum_years": scored_job.minimum_years,
                                "remote": scored_job.remote,
                                "score": match.score,
                                "decision": match.decision,
                                "match_reasons": list(match.reasons),
                                "eligible": eligibility.eligible,
                                "eligibility_reasons": list(eligibility.reasons),
                                "already_applied": already_applied,
                                "application_entry": (
                                    asdict(apply_inspection)
                                    if apply_inspection is not None
                                    else None
                                ),
                                "application_flow": (
                                    asdict(application_flow)
                                    if application_flow is not None
                                    else None
                                ),
                            }
                        )
                    report_path = Path(args.job_report_file)
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
                    print(json.dumps({"jd_inspection_count": len(report), "report": str(report_path)}, indent=2))
                    for item in report:
                        print(json.dumps(item, indent=2))

            print("\nQA runner completed. No applications were submitted.")
            if args.keep_open and not args.headless:
                input("Browser will stay open for inspection. Press Enter to close it... ")
            return 0
    except BrowserRuntimeUnavailable as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
