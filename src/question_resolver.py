from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ResolvedAnswer:
    status: str
    answer: str = ""
    source: str = ""
    normalized_question: str = ""
    reason: str = ""


def normalize_question(value: str) -> str:
    text = str(value or "").lower().replace("*", " ").replace(":", " ")
    return " ".join(text.split())


QUESTION_ALIASES: dict[str, tuple[str, ...]] = {
    "date_of_birth": ("date of birth", "dob", "birth date"),
    "gender": ("gender", "sex"),
    "disability": ("disability", "disability status"),
    "veteran_status": ("veteran status", "protected veteran", "are you a veteran"),
    "ethnicity": ("ethnicity", "hispanic or latino", "hispanic/latino"),
    "race": ("race", "race/ethnicity"),
    "education_level": ("highest education", "highest qualification", "degree"),
    "specialization": ("specialization", "field of study", "major"),
    "university": ("university", "college", "institution"),
    "graduation_date": ("graduation date", "graduation year", "year of graduation"),
    "experience_years": ("total experience", "years of experience", "professional experience"),
    "people_management_years": (
        "people management experience",
        "people-management experience",
        "management experience",
        "team management experience",
    ),
    "shift_flexibility": (
        "shift flexibility",
        "willing to work shifts",
        "night shift",
        "rotational shift",
        "us shift",
    ),
    "travel_percent": ("travel", "travel percentage", "willing to travel"),
    "relocation": ("relocation", "willing to relocate", "open to relocate"),
    "employment_type": ("employment type", "job type", "contract type"),
    "current_ctc": ("current ctc", "current salary", "current compensation"),
    "expected_ctc": ("expected ctc", "expected salary", "expected compensation"),
    "notice_period": ("notice period",),
    "work_authorization": (
        "work authorization",
        "authorized to work",
        "legally authorized to work",
    ),
    "sponsorship_required": (
        "require sponsorship",
        "visa sponsorship",
        "need sponsorship",
    ),
}


def _profile_key_for_question(question: str) -> str:
    normalized = normalize_question(question)
    for key, aliases in QUESTION_ALIASES.items():
        if normalized in aliases:
            return key
    return ""


def _normalize_option(value: str) -> str:
    return " ".join(str(value or "").lower().replace("-", " ").split())


def _match_option(answer: str, options: Sequence[str]) -> str:
    if not options:
        return answer

    wanted = _normalize_option(answer)
    for option in options:
        current = _normalize_option(option)
        if current == wanted:
            return option

    for option in options:
        current = _normalize_option(option)
        if wanted and (wanted in current or current in wanted):
            return option

    yes_values = {"yes", "true", "y"}
    no_values = {"no", "false", "n"}
    if wanted in yes_values:
        for option in options:
            if _normalize_option(option) in yes_values:
                return option
    if wanted in no_values:
        for option in options:
            if _normalize_option(option) in no_values:
                return option

    return ""


def resolve_application_answer(
    question: str,
    profile: Mapping[str, object],
    *,
    options: Sequence[str] = (),
    required: bool = True,
) -> ResolvedAnswer:
    normalized = normalize_question(question)

    custom_answers = profile.get("answers", {})
    if isinstance(custom_answers, Mapping):
        custom = custom_answers.get(normalized)
        if custom not in (None, ""):
            answer = str(custom).strip()
            selected = _match_option(answer, options)
            if options and not selected:
                return ResolvedAnswer(
                    "UNKNOWN_REQUIRED" if required else "UNKNOWN_OPTIONAL",
                    normalized_question=normalized,
                    reason="stored_answer_not_present_in_options",
                )
            return ResolvedAnswer(
                "RESOLVED",
                selected or answer,
                "custom_answer",
                normalized,
            )

    key = _profile_key_for_question(normalized)
    if key:
        value = profile.get(key)
        if value not in (None, ""):
            answer = str(value).strip()
            selected = _match_option(answer, options)
            if options and not selected:
                return ResolvedAnswer(
                    "UNKNOWN_REQUIRED" if required else "UNKNOWN_OPTIONAL",
                    normalized_question=normalized,
                    reason=f"profile_value_not_present_in_options:{key}",
                )
            return ResolvedAnswer(
                "RESOLVED",
                selected or answer,
                f"profile:{key}",
                normalized,
            )

    # EEO questions must never be guessed. If the portal explicitly offers a
    # decline-to-identify option, that is the safe fallback for unknown EEO data.
    eeo_markers = ("gender", "sex", "race", "ethnicity", "disability", "veteran")
    if any(marker in normalized for marker in eeo_markers):
        decline_markers = (
            "do not wish to self identify",
            "do not wish to self-identify",
            "prefer not to say",
            "decline to self identify",
            "decline to self-identify",
        )
        for option in options:
            normalized_option = _normalize_option(option)
            if any(_normalize_option(marker) in normalized_option for marker in decline_markers):
                return ResolvedAnswer(
                    "RESOLVED",
                    option,
                    "eeo_decline_fallback",
                    normalized,
                )

    return ResolvedAnswer(
        "UNKNOWN_REQUIRED" if required else "UNKNOWN_OPTIONAL",
        normalized_question=normalized,
        reason="no_verified_answer",
    )
