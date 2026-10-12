"""One-time, human-controlled Naukri Google sign-in in the agent browser profile.

Do not enter Google credentials in the agent terminal or store Google passwords
in portal_credentials.json. The user completes OAuth in the visible browser.
"""
import argparse
import json
import re

from browser_portals import NaukriBrowserAdapter
from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession


def _safe_session_diagnostics(page) -> dict:
    """Only booleans and counts; no URLs, cookies, names or Google data."""
    try:
        pages = list(page.context.pages)
    except Exception:
        pages = [page]
    naukri_pages = 0
    google_signin_open = False
    profile_route_seen = False
    for candidate in pages:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(str(candidate.url or ""))
            host = (parsed.hostname or "").lower()
            if host == "naukri.com" or host.endswith(".naukri.com"):
                naukri_pages += 1
                profile_route_seen |= parsed.path.startswith("/mnjuser/profile")
            if host == "accounts.google.com":
                google_signin_open = True
        except Exception:
            continue
    return {
        "naukri_tabs": naukri_pages,
        "google_signin_window_open": google_signin_open,
        "naukri_profile_route_seen": profile_route_seen,
    }


def verify_naukri_session(page) -> dict:
    """Re-open Naukri in the same persistent profile to verify logged-in state."""
    adapter = NaukriBrowserAdapter(page)
    try:
        session = adapter.login_state()
    except Exception as exc:
        return {
            "status": "session_verification_failed",
            "reason": f"navigation_failed:{type(exc).__name__}",
        }
    if session.needs_human_action:
        return {
            "status": "human_action_required",
            "reason": session.reason,
        }
    if not session.authenticated:
        return {
            "status": "naukri_session_not_confirmed",
            "reason": session.reason,
            "diagnostics": _safe_session_diagnostics(page),
        }
    return {"status": "naukri_session_verified"}


GOOGLE_SIGN_IN_TEXT = re.compile(
    r"(?:log\s*in|sign\s*in|continue)\s*(?:with|using)?\s*google"
    r"|google\s*(?:log\s*in|sign\s*in)",
    re.IGNORECASE,
)


def start_naukri_google_sign_in(page) -> bool:
    """Click only Naukri's Google OAuth entry point, never Google's prompts.

    OAuth account choice, passwords, consent and MFA are strictly human-operated.
    An absent or changed control does not trigger a guessed fallback action.
    """
    try:
        candidates = (
            page.get_by_role("button", name=GOOGLE_SIGN_IN_TEXT),
            page.get_by_role("link", name=GOOGLE_SIGN_IN_TEXT),
            page.get_by_text(GOOGLE_SIGN_IN_TEXT),
        )
    except (AttributeError, TypeError):
        return False
    for locator in candidates:
        try:
            target = locator.first
            if target.count() and target.is_visible():
                target.click(timeout=5000)
                return True
        except Exception:
            continue
    return False


def setup_google_session(
    profile_dir: str = "browser-profile",
    *,
    prompt=input,
    runtime_factory=PlaywrightSession,
    notify=print,
) -> dict:
    """A deliberate one-time setup, separate from autonomous application runs."""
    config = BrowserRuntimeConfig(user_data_dir=profile_dir, headless=False)
    with runtime_factory(config) as runtime:
        page = runtime.page
        initial = verify_naukri_session(page)
        if initial["status"] == "naukri_session_verified":
            return initial
        if initial["status"] == "human_action_required":
            return initial

        started = start_naukri_google_sign_in(page)
        if started:
            notify(
                "Opened Naukri's Google sign-in control. Select your Google "
                "account in the browser and finish any Google verification yourself. "
                "No account selection or Google security checks are automated."
            )
        else:
            notify(
                "Could not activate Naukri's Google sign-in control automatically. "
                "In the OPENED automation browser, click 'Login with Google' "
                "below Login/Register, then select your Google account yourself. "
                "Do not press Enter until Naukri displays your signed-in profile."
            )
        notify(
            "Use only this automation browser (your normal Chrome session is separate). "
            "Never enter Google credentials in Terminal."
        )
        prompt(
            "After Naukri shows your signed-in profile, press Enter here "
            "to verify the saved session (or Ctrl+C to cancel): "
        )
        return verify_naukri_session(page)


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up Naukri Google sign-in in the agent browser")
    parser.add_argument("--profile-dir", default="browser-profile")
    args = parser.parse_args()
    try:
        result = setup_google_session(args.profile_dir)
    except BrowserRuntimeUnavailable as exc:
        result = {"status": "browser_runtime_unavailable", "reason": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "naukri_session_verified" else 4


if __name__ == "__main__":
    raise SystemExit(main())
