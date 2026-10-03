from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from portal_policy import evaluate_application_safety


@dataclass(frozen=True)
class FormField:
    key: str
    label: str
    required: bool = False
    field_type: str = "text"


@dataclass(frozen=True)
class FillPlan:
    values: dict[str, str] = field(default_factory=dict)
    unknown_required_fields: tuple[str, ...] = ()
    missing_profile_values: tuple[str, ...] = ()
    resume_path: str = ""
    can_fill: bool = False
    can_submit: bool = False
    reasons: tuple[str, ...] = ()


FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "full_name": ("full name", "name"),
    "first_name": ("first name",),
    "last_name": ("last name", "surname"),
    "email": ("email", "email address"),
    "phone": ("phone", "mobile", "mobile number", "phone number", "mobile phone number"),
    "phone_country_code": ("phone country code", "country code", "mobile country code"),
    "location": ("location", "city", "current location"),
    "linkedin": ("linkedin", "linkedin profile", "linkedin url"),
    "notice_period": ("notice period",),
    "notice_period_days": ("notice period in days", "notice period (in days)"),
    "experience_years": ("experience", "years of experience", "total experience"),
    "current_company": ("current company", "company"),
    "current_title": ("current title", "job title", "designation"),
    "current_ctc": ("current ctc", "current salary", "current compensation"),
    "current_ctc_inr": (
        "current annual ctc in inr",
        "current annual ctc (in inr)",
        "current ctc in inr",
    ),
    "expected_ctc": ("expected ctc", "expected salary", "expected compensation"),
    "expected_ctc_inr": (
        "expected annual ctc in inr",
        "expected annual ctc (in inr)",
        "expected ctc in inr",
    ),
}


def _normalize_label(value: str) -> str:
    return " ".join(value.lower().replace("*", " ").replace(":", " ").split())


def resolve_profile_key(label: str) -> Optional[str]:
    normalized = _normalize_label(label)
    for key, aliases in FIELD_ALIASES.items():
        if normalized in aliases:
            return key
    return None


def validate_resume_path(path: str) -> tuple[bool, str]:
    if not path:
        return False, "resume_path_missing"
    target = Path(path)
    if not target.exists() or not target.is_file():
        return False, "resume_file_not_found"
    if target.suffix.lower() not in {".pdf", ".doc", ".docx"}:
        return False, "resume_file_type_unsupported"
    if target.stat().st_size <= 0:
        return False, "resume_file_empty"
    return True, ""


def build_fill_plan(
    fields: tuple[FormField, ...],
    profile: Mapping[str, object],
    *,
    resume_path: str = "",
    captcha_present: bool = False,
    manual_auth_required: bool = False,
    duplicate: bool = False,
    live_submission_enabled: bool = False,
) -> FillPlan:
    values: dict[str, str] = {}
    unknown_required: list[str] = []
    missing_profile: list[str] = []
    needs_resume = False

    for field in fields:
        label = _normalize_label(field.label)
        if field.field_type == "file" or label in {"resume", "cv"}:
            needs_resume = True
            continue

        profile_key = resolve_profile_key(field.label)
        if profile_key is None:
            custom_answers = profile.get("answers", {})
            raw_custom = None
            if isinstance(custom_answers, Mapping):
                raw_custom = custom_answers.get(label)
            if raw_custom not in (None, ""):
                values[field.key] = str(raw_custom)
                continue
            if field.required:
                unknown_required.append(field.label)
            continue

        raw = profile.get(profile_key)
        if raw in (None, ""):
            if field.required:
                missing_profile.append(profile_key)
            continue
        values[field.key] = str(raw)

    reasons: list[str] = []
    if missing_profile:
        reasons.append("required_profile_values_missing")

    selected_resume = ""
    if needs_resume:
        valid_resume, resume_reason = validate_resume_path(resume_path)
        if valid_resume:
            selected_resume = resume_path
        else:
            reasons.append(resume_reason)

    truthful_complete = not missing_profile and not any(
        reason in {
            "resume_path_missing",
            "resume_file_not_found",
            "resume_file_type_unsupported",
            "resume_file_empty",
        }
        for reason in reasons
    )

    safety = evaluate_application_safety(
        live_submission_enabled=live_submission_enabled,
        duplicate=duplicate,
        unknown_required_fields=len(unknown_required),
        captcha_present=captcha_present,
        manual_auth_required=manual_auth_required,
        answers_truthful_and_complete=truthful_complete,
    )

    merged_reasons = tuple(dict.fromkeys([*reasons, *safety.reasons]))
    return FillPlan(
        values=values,
        unknown_required_fields=tuple(unknown_required),
        missing_profile_values=tuple(missing_profile),
        resume_path=selected_resume,
        can_fill=safety.can_fill,
        can_submit=safety.can_submit,
        reasons=merged_reasons,
    )
