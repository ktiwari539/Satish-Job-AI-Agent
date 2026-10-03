import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession
from browser_portals import (
    NaukriBrowserAdapter,
    LinkedInBrowserAdapter,
    classify_linkedin_probe,
    classify_naukri_probe,
)
from jd_enrichment import enrich_job_with_page
from portal_catalog import PORTAL_TARGETS, build_search_url


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
        state = classify_linkedin_probe(page.url)
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
    parser.add_argument("--login-only", action="store_true")
    parser.add_argument("--search-only", action="store_true")
    parser.add_argument("--query", default="Customer Success Manager")
    parser.add_argument("--location", default="India")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    portals = AUTH_PORTALS if args.portal == "all" else (args.portal,)
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

                search = run_search_probe(page, portal, args.query, args.location)
                save_status(args.status_file, search)
                print(json.dumps(asdict(search), indent=2))

                if args.search_only:
                    continue

            print("\nQA runner completed. No applications were submitted.")
            return 0
    except BrowserRuntimeUnavailable as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
