"""One-time, human-controlled Naukri Google sign-in in the agent browser profile.

Do not enter Google credentials in the agent terminal or store Google passwords
in portal_credentials.json. The user completes OAuth in the visible browser.
"""
import argparse
import json

from browser_portals import NaukriBrowserAdapter
from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession


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
        }
    return {"status": "naukri_session_verified"}


def setup_google_session(
    profile_dir: str = "browser-profile",
    *,
    prompt=input,
    runtime_factory=PlaywrightSession,
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

        print(
            "In the opened automation browser, visit Naukri, choose Sign in "
            "with Google, and finish any Google verification yourself. "
            "This browser has a separate persistent profile from your usual Chrome. "
            "Never enter Google credentials in this terminal.",
            flush=True,
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
