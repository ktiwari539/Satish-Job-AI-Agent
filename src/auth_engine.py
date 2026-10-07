from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

from portal_policy import otp_is_eligible


class AuthStage(str, Enum):
    SESSION_CHECK = "SESSION_CHECK"
    LOGIN = "LOGIN"
    SIGNUP = "SIGNUP"
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
    AUTHENTICATED = "AUTHENTICATED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class AuthTransition:
    previous: AuthStage
    current: AuthStage
    reason: str = ""


@dataclass(frozen=True)
class AuthPlan:
    stage: str
    action: str
    reason: str = ""
    can_continue: bool = False
    history: Tuple[str, ...] = field(default_factory=tuple)


class InvalidAuthTransition(RuntimeError):
    pass


_ALLOWED_TRANSITIONS = {
    AuthStage.SESSION_CHECK: {
        AuthStage.LOGIN,
        AuthStage.SIGNUP,
        AuthStage.EMAIL_VERIFICATION,
        AuthStage.AUTHENTICATED,
        AuthStage.BLOCKED,
    },
    AuthStage.LOGIN: {
        AuthStage.EMAIL_VERIFICATION,
        AuthStage.AUTHENTICATED,
        AuthStage.SIGNUP,
        AuthStage.BLOCKED,
    },
    AuthStage.SIGNUP: {
        AuthStage.EMAIL_VERIFICATION,
        AuthStage.AUTHENTICATED,
        AuthStage.BLOCKED,
    },
    AuthStage.EMAIL_VERIFICATION: {
        AuthStage.AUTHENTICATED,
        AuthStage.BLOCKED,
    },
    AuthStage.AUTHENTICATED: set(),
    AuthStage.BLOCKED: set(),
}


class AuthStateMachine:
    def __init__(self) -> None:
        self._stage = AuthStage.SESSION_CHECK
        self._history = []

    @property
    def stage(self) -> AuthStage:
        return self._stage

    @property
    def history(self) -> Tuple[AuthTransition, ...]:
        return tuple(self._history)

    def transition(self, target: AuthStage, *, reason: str = "") -> AuthTransition:
        if target not in _ALLOWED_TRANSITIONS[self._stage]:
            raise InvalidAuthTransition(f"{self._stage.value}->{target.value}")
        event = AuthTransition(self._stage, target, reason)
        self._stage = target
        self._history.append(event)
        return event


def _history(machine: AuthStateMachine) -> Tuple[str, ...]:
    return tuple(
        f"{event.previous.value}->{event.current.value}:{event.reason}"
        for event in machine.history
    )


def plan_authentication(
    session_status: str,
    *,
    account_missing: bool = False,
    email_verification_required: bool = False,
    sign_in_if_needed: bool = True,
    create_account_if_missing: bool = True,
) -> AuthPlan:
    """Create the next safe auth action from a portal session classification.

    This function never handles credentials itself. Credentials remain in the
    local secret provider/browser session. Security challenges always fail closed.
    """
    machine = AuthStateMachine()
    normalized = str(session_status or "").strip().upper()

    if normalized == "SESSION_CONFIRMED":
        machine.transition(AuthStage.AUTHENTICATED, reason="existing_session_verified")
        return AuthPlan(
            stage=machine.stage.value,
            action="CONTINUE",
            can_continue=True,
            history=_history(machine),
        )

    if normalized == "HUMAN_ACTION_REQUIRED":
        machine.transition(AuthStage.BLOCKED, reason="security_challenge_requires_human")
        return AuthPlan(
            stage=machine.stage.value,
            action="STOP",
            reason="security_challenge_requires_human",
            history=_history(machine),
        )

    if normalized == "SESSION_UNVERIFIED":
        machine.transition(AuthStage.BLOCKED, reason="session_state_unverified")
        return AuthPlan(
            stage=machine.stage.value,
            action="STOP",
            reason="session_state_unverified",
            history=_history(machine),
        )

    if normalized != "LOGIN_REQUIRED":
        machine.transition(AuthStage.BLOCKED, reason="unsupported_session_status")
        return AuthPlan(
            stage=machine.stage.value,
            action="STOP",
            reason="unsupported_session_status",
            history=_history(machine),
        )

    if account_missing:
        if not create_account_if_missing:
            machine.transition(AuthStage.BLOCKED, reason="account_missing_signup_disabled")
            return AuthPlan(
                stage=machine.stage.value,
                action="STOP",
                reason="account_missing_signup_disabled",
                history=_history(machine),
            )
        machine.transition(AuthStage.SIGNUP, reason="account_missing")
        if email_verification_required:
            machine.transition(
                AuthStage.EMAIL_VERIFICATION,
                reason="signup_email_verification_required",
            )
            return AuthPlan(
                stage=machine.stage.value,
                action="VERIFY_EMAIL",
                reason="signup_email_verification_required",
                history=_history(machine),
            )
        return AuthPlan(
            stage=machine.stage.value,
            action="CREATE_ACCOUNT",
            reason="account_missing",
            history=_history(machine),
        )

    if not sign_in_if_needed:
        machine.transition(AuthStage.BLOCKED, reason="login_required_signin_disabled")
        return AuthPlan(
            stage=machine.stage.value,
            action="STOP",
            reason="login_required_signin_disabled",
            history=_history(machine),
        )

    machine.transition(AuthStage.LOGIN, reason="login_required")
    if email_verification_required:
        machine.transition(
            AuthStage.EMAIL_VERIFICATION,
            reason="login_email_verification_required",
        )
        return AuthPlan(
            stage=machine.stage.value,
            action="VERIFY_EMAIL",
            reason="login_email_verification_required",
            history=_history(machine),
        )
    return AuthPlan(
        stage=machine.stage.value,
        action="SIGN_IN",
        reason="login_required",
        history=_history(machine),
    )


def can_use_email_otp(
    *,
    sender_matches_portal: bool,
    purpose_matches_login: bool,
    age_seconds: int,
    max_age_seconds: int = 300,
) -> bool:
    return otp_is_eligible(
        sender_matches_portal=sender_matches_portal,
        purpose_matches_login=purpose_matches_login,
        age_seconds=age_seconds,
        max_age_seconds=max_age_seconds,
    )
