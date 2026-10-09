import re
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


def match_answer_to_option(answer: str, options: Sequence[str]) -> str:
    """Return one unambiguous portal option matching a verified answer.

    Matching deliberately avoids raw substring checks. For example, "Male"
    must never match "Female". If more than one option could match, fail closed.
    """
    if not options:
        return answer

    wanted = _normalize_option(answer)
    if not wanted:
        return ""

    exact = [option for option in options if _normalize_option(option) == wanted]
    if len(exact) == 1:
        return exact[0]

    yes_values = {"yes", "true", "y"}
    no_values = {"no", "false", "n"}
    if wanted in yes_values | no_values:
        expected = yes_values if wanted in yes_values else no_values
        boolean_matches = []
        for option in options:
            normalized = _normalize_option(option)
            leading = re.match(r"^([a-z]+)\\b", normalized)
            first = leading.group(1) if leading else ""
            if first in expected:
                boolean_matches.append(option)
        return boolean_matches[0] if len(boolean_matches) == 1 else ""

    # Numeric forms often render "7 years" while the verified fact is "7".
    if re.fullmatch(r"\d+(?:\.\d+)?", wanted):
        numeric_matches = []
        for option in options:
            normalized = _normalize_option(option)
            match = re.match(r"^(\d+(?:\.\d+)?)(?:\b|\s)", normalized)
            if match and match.group(1) == wanted:
                numeric_matches.append(option)
        return numeric_matches[0] if len(numeric_matches) == 1 else ""

    # Allow a verified phrase inside a longer explanatory option only on word
    # boundaries and only when the match is unique.
    pattern = re.compile(r"(?<!\w)" + re.escape(wanted) + r"(?!\w)")
    phrase_matches = [
        option for option in options
        if pattern.search(_normalize_option(option))
    ]
    return phrase_matches[0] if len(phrase_matches) == 1 else ""


def _match_option(answer: str, options: Sequence[str]) -> str:
    return match_answer_to_option(answer, options)


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
