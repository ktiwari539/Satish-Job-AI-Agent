from dataclasses import dataclass, field


@dataclass(frozen=True)
class PortalSpec:
    key: str
    name: str
    discovery_mode: str
    application_mode: str
    login_required: bool = True
    challenge_mode: str = "portal_defined"


@dataclass(frozen=True)
class ApplicationSafety:
    can_fill: bool
    can_submit: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


PORTALS: dict[str, PortalSpec] = {
    "linkedin": PortalSpec("linkedin", "LinkedIn", "authenticated_browser", "authenticated_browser"),
    "naukri": PortalSpec("naukri", "Naukri", "authenticated_browser", "authenticated_browser"),
    "indeed": PortalSpec("indeed", "Indeed", "authenticated_browser", "authenticated_browser"),
    "wellfound": PortalSpec("wellfound", "Wellfound", "authenticated_browser", "authenticated_browser"),
    "glassdoor": PortalSpec("glassdoor", "Glassdoor", "authenticated_browser", "authenticated_browser"),
    "instahyre": PortalSpec("instahyre", "Instahyre", "authenticated_browser", "authenticated_browser"),
    "cutshort": PortalSpec("cutshort", "Cutshort", "authenticated_browser", "authenticated_browser"),
    "foundit": PortalSpec("foundit", "Foundit", "authenticated_browser", "authenticated_browser"),
    "hirist": PortalSpec("hirist", "Hirist", "authenticated_browser", "authenticated_browser"),
    "greenhouse": PortalSpec("greenhouse", "Greenhouse", "public_feed", "browser_form", login_required=False),
    "lever": PortalSpec("lever", "Lever", "public_feed", "browser_form", login_required=False),
}


def evaluate_application_safety(
    *,
    live_submission_enabled: bool,
    duplicate: bool = False,
    unknown_required_fields: int = 0,
    captcha_present: bool = False,
    manual_auth_required: bool = False,
    answers_truthful_and_complete: bool = True,
) -> ApplicationSafety:
    reasons: list[str] = []

    if duplicate:
        reasons.append("duplicate_application")
    if unknown_required_fields > 0:
        reasons.append("unknown_required_fields")
    if captcha_present:
        reasons.append("captcha_requires_human")
    if manual_auth_required:
        reasons.append("manual_auth_required")
    if not answers_truthful_and_complete:
        reasons.append("answers_incomplete_or_unverified")
    if not live_submission_enabled:
        reasons.append("live_submission_disabled")

    fill_blockers = {
        "captcha_requires_human",
        "manual_auth_required",
        "answers_incomplete_or_unverified",
    }
    can_fill = not any(reason in fill_blockers for reason in reasons)
    can_submit = not reasons
    return ApplicationSafety(can_fill=can_fill, can_submit=can_submit, reasons=tuple(reasons))


def otp_is_eligible(
    *,
    sender_matches_portal: bool,
    purpose_matches_login: bool,
    age_seconds: int,
    max_age_seconds: int = 300,
) -> bool:
    if age_seconds < 0:
        return False
    return sender_matches_portal and purpose_matches_login and age_seconds <= max_age_seconds
