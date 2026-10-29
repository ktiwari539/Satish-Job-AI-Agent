import re
from dataclasses import dataclass
from typing import Mapping, Sequence
from work_authorization import is_india_authorization_question


@dataclass(frozen=True)
class ResolvedAnswer:
    status: str
    answer: str = ""
    source: str = ""
    normalized_question: str = ""
    reason: str = ""


def normalize_question(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
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
    "experience_years": (
        "total experience",
        "years of experience",
        "professional experience",
    ),
    "customer_success_years": (
        "customer success experience",
        "years of customer success experience",
        "how many years of experience do you have with customer success?",
        "how many years of experience do you have with customer success",
    ),
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
    "current_ctc": (
        "current ctc",
        "current salary",
        "current compensation",
        "what is your current ctc?",
        "what is your current ctc",
    ),
    "expected_ctc": (
        "expected ctc",
        "expected salary",
        "expected compensation",
        "what is your expected ctc?",
        "what is your expected ctc",
    ),
    "notice_period": (
        "notice period",
        "what is your notice period?",
        "what is your notice period",
    ),
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
        if normalized in (normalize_question(alias) for alias in aliases):
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
            leading = re.match(r"^([a-z]+)\b", normalized)
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


def _resolve_verified_experience_threshold(
    question: str, profile: Mapping[str, object], options: Sequence[str],
) -> ResolvedAnswer:
    """Interpret quantitative experience checks only with an explicit fact.

    This does not infer experience from a job title, resume date, or missing
    skills. A negative response to a threshold is justified only when the
    matching number of years is known and the question is unambiguous.
    """
    normalized = normalize_question(question)
    if not all(token in normalized for token in ("year", "experience")):
        return ResolvedAnswer("UNRESOLVED")
    threshold = re.search(
        r"\b(?:at least|min(?:imum)?|more than|over|above|"
        r"have|possess|of)\s+(\d{1,2})\s*(?:plus|or more)?\s*years?\b"
        r"|\b(\d{1,2})\s*(?:plus|or more)\s*years?\b",
        normalized,
    )
    if not threshold:
        return ResolvedAnswer("UNRESOLVED")
    years = int(next(x for x in threshold.groups() if x is not None))
    # Industry-specific qualifiers are not implied by overall experience.
    # Only overall/total years and precisely-scoped customer success or
    # people-management questions can use their respective profile facts.
    if any(word in normalized for word in (
        "bpo", "insurance", "healthcare", "telesales", "technical",
        "sales operations", "specific industry",
    )):
        return ResolvedAnswer("UNRESOLVED")
    if any(word in normalized for word in ("total", "overall", "professional")):
        key = "experience_years"
    elif "customer success" in normalized:
        key = "customer_success_years"
    elif any(word in normalized for word in (
        "team management", "people management", "managing teams",
    )):
        key = "people_management_years"
    else:
        return ResolvedAnswer("UNRESOLVED")
    raw = profile.get(key)
    if key == "experience_years" and raw in (None, ""):
        raw = profile.get("total_experience_years")
    try:
        actual = float(str(raw).strip())
    except (TypeError, ValueError):
        return ResolvedAnswer("UNRESOLVED")
    if actual < 0 or actual > 80:
        return ResolvedAnswer("UNRESOLVED")
    # "More than/over/above N" is strict; "minimum/at least N" is
    # inclusive. Avoid overstating an applicant's experience at the boundary.
    strictly_more = bool(re.search(
        r"\b(?:more than|over|above)\s+" + str(years) + r"\s*years?\b",
        normalized,
    ))
    answer = "Yes" if (actual > years if strictly_more else actual >= years) else "No"
    selected = match_answer_to_option(answer, options)
    if options and not selected:
        return ResolvedAnswer("UNRESOLVED")
    return ResolvedAnswer(
        "RESOLVED", selected or answer, "verified_experience_threshold",
        normalized,
    )


def _verified_india_authorization_answer(
    question: str, profile: Mapping[str, object], options: Sequence[str],
) -> ResolvedAnswer:
    """Use only the applicant's explicit India authorization fact.

    Do not confuse work authorization with employer sponsorship or assume
    authorization in another country.
    """
    normalized = normalize_question(question)
    if not is_india_authorization_question(question):
        return ResolvedAnswer("UNRESOLVED")
    raw = profile.get("india_authorized")
    if type(raw) is not bool:
        return ResolvedAnswer("UNRESOLVED")
    answer = "Yes" if raw else "No"
    selected = match_answer_to_option(answer, options)
    if options and not selected:
        return ResolvedAnswer("UNRESOLVED")
    return ResolvedAnswer(
        "RESOLVED", selected or answer, "verified_india_work_authorization",
        normalized,
    )


def _resolve_profile_quantity(
    question: str, profile: Mapping[str, object], options: Sequence[str],
) -> ResolvedAnswer:
    """Answer open numeric questions without an LLM or inference.

    Only scope-specific, applicant-provided values are eligible. In
    particular, overall years may not stand in for a technology or industry
    experience question. Threshold yes/no questions are handled separately.
    """
    normalized = normalize_question(question)
    if not any(t in normalized for t in (
        "how many", "number of", "what is", "state your", "specify your",
    )):
        return ResolvedAnswer("UNRESOLVED")
    if re.search(r"\b(?:minimum|at least|more than|over|above)\s+\d+", normalized):
        return ResolvedAnswer("UNRESOLVED")
    key = ""
    if "years" in normalized and "experience" in normalized:
        if "customer success" in normalized or "client success" in normalized:
            key = "customer_success_years"
        elif any(t in normalized for t in (
            "people management", "managing teams", "team management",
        )):
            key = "people_management_years"
        elif any(t in normalized for t in (
            "overall", "total", "professional",
        )):
            if not any(t in normalized for t in (
                "bpo", "insurance", "sales", "healthcare", "technical",
                "using", "with", "in the",
            )):
                key = "experience_years"
    elif (
        ("how many days" in normalized or "number of days" in normalized)
        and any(t in normalized for t in ("join", "joining", "start"))
    ):
        key = "notice_period_days"
    if not key:
        return ResolvedAnswer("UNRESOLVED")
    value = profile.get(key)
    if key == "experience_years" and value in (None, ""):
        value = profile.get("total_experience_years")
    if value in (None, "") or type(value) not in (str, int, float):
        return ResolvedAnswer("UNRESOLVED")
    raw = str(value).strip()
    if not re.fullmatch(r"\d{1,3}(?:\.\d{1,2})?", raw):
        return ResolvedAnswer("UNRESOLVED")
    selected = match_answer_to_option(raw, options)
    if options and not selected:
        return ResolvedAnswer("UNRESOLVED")
    return ResolvedAnswer("RESOLVED", selected or raw,
                          "verified_profile_quantity:" + key, normalized)


def resolve_application_answer(
    question: str,
    profile: Mapping[str, object],
    *,
    options: Sequence[str] = (),
    required: bool = True,
) -> ResolvedAnswer:
    normalized = normalize_question(question)

    from sheet_control import resolve_control_answer
    controlled=resolve_control_answer(question,profile,options,required)
    if controlled is not None:
        return ResolvedAnswer(**controlled)

    custom_answers = profile.get("answers", {})
    if isinstance(custom_answers, Mapping):
        custom = custom_answers.get(normalized)
        if custom in (None, ""):
            # Preserve existing custom answers stored under legacy punctuation.
            matches = [
                value for key, value in custom_answers.items()
                if normalize_question(key) == normalized and value not in (None, "")
            ]
            if len(matches) == 1:
                custom = matches[0]
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

    # Common open numeric questions are grounded directly without any AI.
    quantity = _resolve_profile_quantity(question, profile, options)
    if quantity.status == "RESOLVED":
        return quantity

    # Only safely scoped boolean and quantitative facts may be inferred
    # from an explicit private profile value; no cross-country assumptions.
    authorization_answer = _verified_india_authorization_answer(
        question, profile, options
    )
    if authorization_answer.status == "RESOLVED":
        return authorization_answer

    # A limited semantic answer can be derived from explicit profile years.
    # All other unrecognized questions still require applicant evidence.
    threshold_answer = _resolve_verified_experience_threshold(
        question, profile, options
    )
    if threshold_answer.status == "RESOLVED":
        return threshold_answer

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

    # Optional localhost-only language model. It may map unfamiliar
    # wording to an ALREADY VERIFIED fact key, but cannot supply a free-form
    # answer. The fact's semantic scope and option text are revalidated in
    # Python. It is disabled unless the applicant opts in with --local-model.
    # Imported lazily to leave normal QA and CI without model dependencies.
    try:
        from grounded_reasoner import resolve_with_local_reasoner
        local = resolve_with_local_reasoner(question, profile, options)
    except Exception:
        local = None
    if local is not None and local.state == "resolved":
        return ResolvedAnswer(
            "RESOLVED", local.answer,
            "local_verified_fact:" + local.fact_key,
            normalized,
        )

    return ResolvedAnswer(
        "UNKNOWN_REQUIRED" if required else "UNKNOWN_OPTIONAL",
        normalized_question=normalized,
        reason="no_verified_answer",
    )
