from dataclasses import dataclass, field
from typing import Optional, Tuple

from auth_engine import plan_authentication
from browser_portals import classify_linkedin_probe


@dataclass(frozen=True)
class BrowserAuthCredentials:
    email: str
    password: str

    def is_complete(self) -> bool:
        return bool(self.email.strip() and self.password)


@dataclass(frozen=True)
class BrowserAuthResult:
    state: str
    action: str = ""
    reason: str = ""
    authenticated: bool = False
    current_url: str = ""
    history: Tuple[str, ...] = field(default_factory=tuple)


def _first_usable(page, selectors: Tuple[str, ...]):
    for selector in selectors:
        try:
            target = page.locator(selector).first
            if target.count() and target.is_visible() and target.is_enabled():
                return target, selector
        except Exception:
            continue
    return None, ""


def _body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=5000)
    except Exception:
        return ""


def _linkedin_account_missing(body_text: str) -> bool:
    text = " ".join(str(body_text or "").lower().split())
    markers = (
        "couldn't find a linkedin account",
        "could not find a linkedin account",
        "no linkedin account",
        "account doesn't exist",
        "account does not exist",
    )
    return any(marker in text for marker in markers)


def execute_linkedin_sign_in(
    page,
    credentials: BrowserAuthCredentials,
    *,
    navigate_to_login: bool = True,
) -> BrowserAuthResult:
    """Attempt a normal LinkedIn sign-in using only locally supplied secrets.

    No credential value is returned, logged, or written to disk. CAPTCHA,
    checkpoints, MFA, and other security challenges fail closed.
    """
    if not credentials.is_complete():
        return BrowserAuthResult(
            state="BLOCKED",
            action="STOP",
            reason="local_credentials_missing",
            current_url=getattr(page, "url", ""),
        )

    if navigate_to_login:
        try:
            page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        except Exception as exc:
            return BrowserAuthResult(
                state="BLOCKED",
                action="STOP",
                reason=f"login_page_open_failed:{type(exc).__name__}",
                current_url=getattr(page, "url", ""),
            )

    username, username_selector = _first_usable(
        page,
        (
            "#username",
            "input[name='session_key']",
            "input[autocomplete='username']",
            "input[type='email']",
        ),
    )
    password, password_selector = _first_usable(
        page,
        (
            "#password",
            "input[name='session_password']",
            "input[autocomplete='current-password']",
            "input[type='password']",
        ),
    )
    submit, submit_selector = _first_usable(
        page,
        (
            "button[type='submit']",
            "button:text-is('Sign in')",
            "button:has-text('Sign in')",
        ),
    )

    missing = []
    if username is None:
        missing.append("username")
    if password is None:
        missing.append("password")
    if submit is None:
        missing.append("submit")
    if missing:
        return BrowserAuthResult(
            state="BLOCKED",
            action="STOP",
            reason="login_controls_not_found:" + ",".join(missing),
            current_url=getattr(page, "url", ""),
            history=tuple(
                value for value in (
                    f"username_selector:{username_selector}" if username_selector else "",
                    f"password_selector:{password_selector}" if password_selector else "",
                    f"submit_selector:{submit_selector}" if submit_selector else "",
                )
                if value
            ),
        )

    try:
        username.fill(credentials.email)
        password.fill(credentials.password)
        submit.click(timeout=5000)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            page.wait_for_timeout(1200)
    except Exception as exc:
        return BrowserAuthResult(
            state="BLOCKED",
            action="STOP",
            reason=f"login_action_failed:{type(exc).__name__}",
            current_url=getattr(page, "url", ""),
        )

    body = _body_text(page)
    state = classify_linkedin_probe(getattr(page, "url", ""), body)

    if state.needs_human_action:
        return BrowserAuthResult(
            state="BLOCKED",
            action="STOP",
            reason=state.reason or "security_challenge_requires_human",
            current_url=getattr(page, "url", ""),
        )

    if state.authenticated:
        return BrowserAuthResult(
            state="AUTHENTICATED",
            action="CONTINUE",
            authenticated=True,
            current_url=getattr(page, "url", ""),
            history=("LOGIN->AUTHENTICATED:session_verified_after_signin",),
        )

    if _linkedin_account_missing(body):
        return BrowserAuthResult(
            state="SIGNUP_REQUIRED",
            action="CREATE_ACCOUNT",
            reason="linkedin_account_not_found",
            current_url=getattr(page, "url", ""),
            history=("LOGIN->SIGNUP:account_not_found",),
        )

    return BrowserAuthResult(
        state="BLOCKED",
        action="STOP",
        reason=state.reason or "linkedin_login_not_confirmed",
        current_url=getattr(page, "url", ""),
    )


def execute_linkedin_auth(
    page,
    session_status: str,
    credentials: Optional[BrowserAuthCredentials] = None,
) -> BrowserAuthResult:
    """Execute the currently supported LinkedIn auth action.

    Existing sessions continue immediately. Login is automated when credentials
    are supplied locally. Account creation is surfaced as the next state but is
    intentionally not fabricated: signup execution will be a separate adapter
    because LinkedIn may require email verification and security challenges.
    """
    plan = plan_authentication(session_status)

    if plan.can_continue:
        return BrowserAuthResult(
            state="AUTHENTICATED",
            action="CONTINUE",
            authenticated=True,
            current_url=getattr(page, "url", ""),
            history=plan.history,
        )

    if plan.action == "SIGN_IN":
        if credentials is None:
            return BrowserAuthResult(
                state="BLOCKED",
                action="STOP",
                reason="local_credentials_missing",
                current_url=getattr(page, "url", ""),
                history=plan.history,
            )
        return execute_linkedin_sign_in(page, credentials)

    return BrowserAuthResult(
        state=plan.stage,
        action=plan.action,
        reason=plan.reason,
        authenticated=False,
        current_url=getattr(page, "url", ""),
        history=plan.history,
    )
