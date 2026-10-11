from dataclasses import dataclass
from typing import Mapping, Optional

from agent_trace import trace_event, trace_step
from local_credentials import PortalCredentials


@dataclass(frozen=True)
class PortalAccountResult:
    state: str
    authenticated: bool = False
    created: bool = False
    reason: str = ""
    action: str = ""
    current_url: str = ""


def _body_text(page) -> str:
    try:
        return " ".join(page.locator("body").inner_text(timeout=4000).split())
    except Exception:
        return ""


def _first_usable(page, selectors: tuple[str, ...]):
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), 12)
            for index in range(count):
                target = locator.nth(index)
                if target.is_visible() and target.is_enabled():
                    return target, selector
        except Exception:
            continue
    return None, ""


def _security_challenge(text: str) -> str:
    lowered = text.lower()
    markers = (
        ("captcha", "captcha_requires_human"),
        ("verify you are human", "human_verification_required"),
        ("verify you're human", "human_verification_required"),
        ("authenticator", "authenticator_mfa_required"),
        ("security key", "security_key_required"),
        ("biometric", "biometric_required"),
        ("two-factor", "mfa_required"),
        ("2-step verification", "mfa_required"),
    )
    for marker, reason in markers:
        if marker in lowered:
            return reason
    return ""


def _email_verification_required(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "verify your email",
        "verify email",
        "check your email",
        "check your inbox",
        "verification code",
        "email verification",
        "we sent you a code",
    )
    return any(marker in lowered for marker in markers)


def _account_missing(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "account not found",
        "no account found",
        "couldn't find an account",
        "could not find an account",
        "email is not registered",
        "user not found",
        "create an account",
        "sign up to continue",
    )
    return any(marker in lowered for marker in markers)


def _looks_like_signup(text: str, page) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in ("create account", "sign up", "register")):
        try:
            if page.locator(
                "input[autocomplete='new-password'], "
                "input[name*='confirm'][type='password'], "
                "input[id*='confirm'][type='password']"
            ).count():
                return True
        except Exception:
            pass
    return False


def _fill_if_present(page, selectors: tuple[str, ...], value: str) -> bool:
    if not value:
        return False
    target, _ = _first_usable(page, selectors)
    if target is None:
        return False
    try:
        target.fill(value)
        return True
    except Exception:
        return False


def _accept_required_processing_terms(page) -> None:
    """Accept only required application/privacy/terms consent, never marketing."""
    script = r"""
    () => Array.from(document.querySelectorAll('input[type="checkbox"]'))
      .filter((el) => !el.disabled && !el.checked)
      .map((el) => {
        const id = el.id || '';
        let label = '';
        if (id) {
          const node = document.querySelector('label[for="' + CSS.escape(id) + '"]');
          if (node) label = node.innerText || node.textContent || '';
        }
        if (!label) {
          const wrap = el.closest('label');
          if (wrap) label = wrap.innerText || wrap.textContent || '';
        }
        if (!label) {
          const container = el.closest('[class*="field"], [class*="form"], div');
          if (container) label = container.innerText || container.textContent || '';
        }
        return {
          id,
          name: el.name || '',
          required: !!el.required || el.getAttribute('aria-required') === 'true',
          label: (label || '').replace(/\s+/g, ' ').trim()
        };
      })
    """
    try:
        rows = page.evaluate(script) or []
    except Exception:
        return

    allowed = ("terms", "privacy", "data processing", "candidate consent", "consent")
    blocked = ("marketing", "newsletter", "promotional", "job alerts", "similar jobs")
    for row in rows:
        label = str(row.get("label", "") or "").lower()
        if not row.get("required"):
            continue
        if not any(marker in label for marker in allowed):
            continue
        if any(marker in label for marker in blocked):
            continue
        name = str(row.get("name", "") or "")
        element_id = str(row.get("id", "") or "")
        selectors = []
        if element_id:
            selectors.append(f'input[type="checkbox"][id="{element_id}"]')
        if name:
            selectors.append(f'input[type="checkbox"][name="{name}"]')
        for selector in selectors:
            try:
                target = page.locator(selector).first
                if target.count() and target.is_visible() and target.is_enabled():
                    target.check(timeout=2000)
                    break
            except Exception:
                continue


def _wait_after_auth_action(page, timeout_ms: int = 6000) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except Exception:
        pass
    try:
        page.wait_for_timeout(900)
    except Exception:
        pass


def _find_login_controls(page):
    email, _ = _first_usable(
        page,
        (
            "input[type='email']",
            "input[autocomplete='email']",
            "input[autocomplete='username']",
            "input[name*='email']",
            "input[id*='email']",
            "input[name*='user']",
        ),
    )
    password, _ = _first_usable(
        page,
        (
            "input[type='password']",
            "input[autocomplete='current-password']",
        ),
    )
    submit, _ = _first_usable(
        page,
        (
            "button[type='submit']:has-text('Sign in')",
            "button[type='submit']:has-text('Log in')",
            "button:has-text('Sign in')",
            "button:has-text('Log in')",
            "input[type='submit'][value*='Sign in']",
            "input[type='submit'][value*='Log in']",
        ),
    )
    return email, password, submit


def _find_signup_control(page):
    return _first_usable(
        page,
        (
            "a:has-text('Create account')",
            "button:has-text('Create account')",
            "a:has-text('Sign up')",
            "button:has-text('Sign up')",
            "a:has-text('Register')",
            "button:has-text('Register')",
        ),
    )[0]


def _execute_signup(
    page,
    profile: Mapping[str, object],
    credentials: PortalCredentials,
) -> PortalAccountResult:
    text = _body_text(page)
    challenge = _security_challenge(text)
    if challenge:
        return PortalAccountResult(
            "HUMAN_ACTION_REQUIRED",
            reason=challenge,
            action="COMPLETE_SECURITY_CHALLENGE",
            current_url=str(getattr(page, "url", "") or ""),
        )

    signup = _find_signup_control(page)
    if signup is not None and not _looks_like_signup(text, page):
        try:
            with trace_step("external_account_open_signup"):
                signup.click(timeout=5000)
                _wait_after_auth_action(page)
        except Exception as exc:
            return PortalAccountResult(
                "BLOCKED",
                reason=f"signup_open_failed:{type(exc).__name__}",
                action="STOP",
                current_url=str(getattr(page, "url", "") or ""),
            )

    first_name = str(profile.get("first_name", "") or "")
    last_name = str(profile.get("last_name", "") or "")
    full_name = str(profile.get("full_name", "") or "")

    _fill_if_present(
        page,
        ("input[name*='first']", "input[id*='first']", "input[autocomplete='given-name']"),
        first_name,
    )
    _fill_if_present(
        page,
        ("input[name*='last']", "input[id*='last']", "input[autocomplete='family-name']"),
        last_name,
    )
    _fill_if_present(
        page,
        ("input[name*='name']", "input[id*='name']", "input[autocomplete='name']"),
        full_name,
    )
    _fill_if_present(
        page,
        ("input[type='email']", "input[name*='email']", "input[id*='email']"),
        credentials.email,
    )
    _fill_if_present(
        page,
        (
            "input[autocomplete='new-password']",
            "input[type='password']",
        ),
        credentials.password,
    )

    try:
        passwords = page.locator("input[type='password']")
        if passwords.count() >= 2:
            passwords.nth(0).fill(credentials.password)
            passwords.nth(1).fill(credentials.password)
    except Exception:
        pass

    _accept_required_processing_terms(page)

    submit, _ = _first_usable(
        page,
        (
            "button[type='submit']:has-text('Create account')",
            "button[type='submit']:has-text('Sign up')",
            "button[type='submit']:has-text('Register')",
            "button:has-text('Create account')",
            "button:has-text('Sign up')",
            "button:has-text('Register')",
            "input[type='submit'][value*='Create']",
            "input[type='submit'][value*='Register']",
        ),
    )
    if submit is None:
        return PortalAccountResult(
            "BLOCKED",
            reason="signup_controls_not_found",
            action="STOP",
            current_url=str(getattr(page, "url", "") or ""),
        )

    try:
        with trace_step("external_account_create"):
            submit.click(timeout=5000)
            _wait_after_auth_action(page)
    except Exception as exc:
        return PortalAccountResult(
            "BLOCKED",
            reason=f"signup_submit_failed:{type(exc).__name__}",
            action="STOP",
            current_url=str(getattr(page, "url", "") or ""),
        )

    text = _body_text(page)
    challenge = _security_challenge(text)
    if challenge:
        return PortalAccountResult(
            "HUMAN_ACTION_REQUIRED",
            reason=challenge,
            action="COMPLETE_SECURITY_CHALLENGE",
            current_url=str(getattr(page, "url", "") or ""),
        )
    if _email_verification_required(text):
        return PortalAccountResult(
            "HUMAN_ACTION_REQUIRED",
            created=True,
            reason="email_verification_required",
            action="VERIFY_EMAIL",
            current_url=str(getattr(page, "url", "") or ""),
        )

    _, password, _ = _find_login_controls(page)
    if password is None:
        return PortalAccountResult(
            "AUTHENTICATED",
            authenticated=True,
            created=True,
            action="CONTINUE",
            current_url=str(getattr(page, "url", "") or ""),
        )
    return PortalAccountResult(
        "BLOCKED",
        created=True,
        reason="signup_not_confirmed",
        action="STOP",
        current_url=str(getattr(page, "url", "") or ""),
    )


def ensure_external_portal_account(
    page,
    profile: Mapping[str, object],
    credentials: Optional[PortalCredentials],
    *,
    create_account_if_missing: bool,
) -> PortalAccountResult:
    """Sign in or create a simple ATS account when the apply flow requires it.

    CAPTCHA, MFA, security-key, biometric, and email-verification challenges are
    surfaced as human-action checkpoints. They are never bypassed.
    """
    text = _body_text(page)
    challenge = _security_challenge(text)
    if challenge:
        return PortalAccountResult(
            "HUMAN_ACTION_REQUIRED",
            reason=challenge,
            action="COMPLETE_SECURITY_CHALLENGE",
            current_url=str(getattr(page, "url", "") or ""),
        )

    email, password, submit = _find_login_controls(page)
    signup = _find_signup_control(page)

    if email is None and password is None and signup is None:
        return PortalAccountResult(
            "NOT_REQUIRED",
            authenticated=True,
            action="CONTINUE",
            current_url=str(getattr(page, "url", "") or ""),
        )

    if credentials is None or not credentials.complete():
        return PortalAccountResult(
            "BLOCKED",
            reason="external_account_credentials_missing",
            action="STOP",
            current_url=str(getattr(page, "url", "") or ""),
        )

    if _looks_like_signup(text, page):
        if not create_account_if_missing:
            return PortalAccountResult(
                "BLOCKED",
                reason="account_missing_signup_disabled",
                action="STOP",
                current_url=str(getattr(page, "url", "") or ""),
            )
        return _execute_signup(page, profile, credentials)

    if email is not None and password is not None and submit is not None:
        try:
            with trace_step("external_account_sign_in"):
                email.fill(credentials.email)
                password.fill(credentials.password)
                submit.click(timeout=5000)
                _wait_after_auth_action(page)
        except Exception as exc:
            return PortalAccountResult(
                "BLOCKED",
                reason=f"external_login_failed:{type(exc).__name__}",
                action="STOP",
                current_url=str(getattr(page, "url", "") or ""),
            )

        text = _body_text(page)
        challenge = _security_challenge(text)
        if challenge:
            return PortalAccountResult(
                "HUMAN_ACTION_REQUIRED",
                reason=challenge,
                action="COMPLETE_SECURITY_CHALLENGE",
                current_url=str(getattr(page, "url", "") or ""),
            )
        if _email_verification_required(text):
            return PortalAccountResult(
                "HUMAN_ACTION_REQUIRED",
                reason="email_verification_required",
                action="VERIFY_EMAIL",
                current_url=str(getattr(page, "url", "") or ""),
            )

        _, remaining_password, _ = _find_login_controls(page)
        if remaining_password is None:
            return PortalAccountResult(
                "AUTHENTICATED",
                authenticated=True,
                action="CONTINUE",
                current_url=str(getattr(page, "url", "") or ""),
            )

        if _account_missing(text) and create_account_if_missing:
            return _execute_signup(page, profile, credentials)

        return PortalAccountResult(
            "BLOCKED",
            reason="external_login_not_confirmed",
            action="STOP",
            current_url=str(getattr(page, "url", "") or ""),
        )

    if signup is not None:
        if not create_account_if_missing:
            return PortalAccountResult(
                "BLOCKED",
                reason="account_missing_signup_disabled",
                action="STOP",
                current_url=str(getattr(page, "url", "") or ""),
            )
        return _execute_signup(page, profile, credentials)

    return PortalAccountResult(
        "BLOCKED",
        reason="external_auth_controls_incomplete",
        action="STOP",
        current_url=str(getattr(page, "url", "") or ""),
    )
