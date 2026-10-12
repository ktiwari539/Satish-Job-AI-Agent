"""One-time, human-controlled Naukri account login in the agent browser profile.

Prefer Naukri OTP. Google OAuth may reject automated browsers; never circumvent
Google security checks or store account passwords/OTPs in portal_credentials.json.
"""
import argparse
import json
import re
from urllib.parse import urlparse

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


class GoogleOAuthObserver:
    """Track whether a genuine OAuth navigation happened, without saving URLs."""
    def __init__(self, page):
        self.page = page
        self.new_window_seen = False
        self.google_auth_seen = False
        self.google_auth_in_main_tab = False
        self._attached = set()
        self._attach(page)
        try:
            page.context.on("page", self._new_page)
        except (AttributeError, TypeError):
            pass

    def _url(self, url, *, main=False):
        try:
            host = (urlparse(str(url or "")).hostname or "").lower()
        except (TypeError, ValueError):
            return
        if host == "accounts.google.com":
            self.google_auth_seen = True
            if main:
                self.google_auth_in_main_tab = True

    def _frame(self, frame, *, main=False):
        self._url(getattr(frame, "url", ""), main=main)

    def _attach(self, page):
        if id(page) in self._attached:
            return
        self._attached.add(id(page))
        self._url(getattr(page, "url", ""), main=(page is self.page))
        try:
            page.on(
                "framenavigated",
                lambda frame: self._frame(frame, main=(page is self.page)),
            )
        except (AttributeError, TypeError):
            pass

    def _new_page(self, page):
        if page is not self.page:
            self.new_window_seen = True
        self._attach(page)

    def snapshot(self) -> dict:
        try:
            pages = list(self.page.context.pages)
        except (AttributeError, TypeError):
            pages = [self.page]
        for page in pages:
            self._attach(page)
            self._url(getattr(page, "url", ""), main=(page is self.page))
        return {
            "google_auth_page_seen": self.google_auth_seen,
            "oauth_new_window_seen": self.new_window_seen,
            "google_auth_in_main_tab": self.google_auth_in_main_tab,
        }


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

        observer = GoogleOAuthObserver(page)
        started = start_naukri_google_sign_in(page)
        if started:
            notify(
                "Clicked Naukri's 'Login with Google' control. A click does NOT "
                "mean Google sign-in succeeded. Look for a Google account chooser "
                "in the opened browser (including another window or tab)."
            )
        else:
            notify(
                "Could not click Naukri's Google control. In the automation "
                "browser, click 'Login with Google' yourself."
            )
        # Give popups and same-tab redirects time to register, without selecting
        # accounts, bypassing Google prompts, or waiting for a network response.
        try:
            page.wait_for_timeout(1000)
        except (AttributeError, TypeError):
            pass
        notify("OAuth navigation diagnostic (no personal data): " +
               json.dumps(observer.snapshot(), sort_keys=True))
        notify(
            "Select your Google account only in the automation browser. "
            "Do not press Enter until Naukri visibly shows your signed-in "
            "profile. If Google displays a security/browser error, stop there "
            "and do not attempt to bypass it."
        )
        prompt(
            "After Naukri shows your signed-in profile, press Enter here "
            "to verify (or Ctrl+C to cancel): "
        )
        before_verify = observer.snapshot()
        verified = verify_naukri_session(page)
        if verified["status"] != "naukri_session_verified":
            verified["oauth_diagnostics"] = before_verify
        return verified


def setup_otp_session(
    profile_dir: str = "browser-profile",
    *,
    prompt=input,
    runtime_factory=PlaywrightSession,
    notify=print,
) -> dict:
    """Allow a person to use Naukri's own OTP login in the agent browser.

    No Google OAuth, OTP reading, automatic challenge handling, or secret export.
    This may not be offered to all accounts; fail closed if it does not work.
    """
    config = BrowserRuntimeConfig(user_data_dir=profile_dir, headless=False)
    with runtime_factory(config) as runtime:
        page = runtime.page
        initial = verify_naukri_session(page)
        if initial["status"] in ("naukri_session_verified", "human_action_required"):
            return initial

        try:
            page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded")
        except Exception as exc:
            return {"status": "login_page_navigation_failed",
                    "reason": "navigation_failed:" + type(exc).__name__}
        notify(
            "In the opened Naukri browser, choose 'Use OTP to Login', "
            "enter the email address attached to your Naukri account, and "
            "complete the OTP yourself. Do not choose Google sign-in here. "
            "If Naukri does not support OTP for this account, stop without "
            "changing your account or sharing any OTP with the agent."
        )
        prompt(
            "Press Enter ONLY after Naukri visibly shows your signed-in "
            "profile (or Ctrl+C to cancel): "
        )
        return verify_naukri_session(page)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set up human-controlled Naukri OTP login in the agent browser"
    )
    parser.add_argument("--profile-dir", default="browser-profile")
    parser.add_argument("--method", choices=("otp",), default="otp",
                        help="Supported account login method. Google OAuth is blocked in the automation browser.")
    args = parser.parse_args()
    try:
        result = setup_otp_session(args.profile_dir)
    except BrowserRuntimeUnavailable as exc:
        result = {"status": "browser_runtime_unavailable", "reason": str(exc)}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "naukri_session_verified" else 4


if __name__ == "__main__":
    raise SystemExit(main())
