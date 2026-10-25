"""Opt-in, localhost-only language model for profile-grounded form answers.

The model may ONLY identify which already verified applicant fact a question
is asking about. It cannot supply the answer. A deterministic validator checks
the fact's scope and converts the original, unmodified fact to a portal option.
No remote provider endpoints, credentials, cookies or resume contents.

Without an explicitly configured local model, this module is a read-only
NO-OP and the conventional resolver remains the default.
"""
from dataclasses import dataclass
import json
import re
from typing import Mapping, Sequence
from urllib import request, error


_LOCAL_ENDPOINT = "http://127.0.0.1:11434/api/generate"

# Do not make sensitive demographic or legal conclusions by semantic analogy.
# Standard contact fields are excluded: their exact-label mapping already
# exists, and they needn't be passed through a language model.
_FACT_FAMILIES = {
    "experience_years": "overall_experience",
    "total_experience_years": "overall_experience",
    "customer_success_years": "customer_success_experience",
    "people_management_years": "people_management_experience",
    "notice_period": "notice",
    "notice_period_days": "notice",
    "current_ctc": "current_salary",
    "current_ctc_inr": "current_salary",
    "expected_ctc": "expected_salary",
    "expected_ctc_inr": "expected_salary",
    "current_company": "current_employer",
    "current_title": "current_role",
    "education_level": "education",
    "university": "university",
    "graduation_date": "graduation",
    "employment_type": "employment_type",
}
# A model cannot infer an explicit YES/NO eligibility assertion from an
# unrelated string (e.g. overall experience does NOT prove BPO experience).
_FAMILY_TERMS = {
    "overall_experience": ("experience", "years", "total", "overall", "professional"),
    "customer_success_experience": ("customer success", "client success"),
    "people_management_experience": ("people management", "team management", "managing people", "managing teams"),
    "notice": ("notice", "join", "available to start", "availability", "joining"),
    "current_salary": ("current salary", "current ctc", "currently earn", "present compensation"),
    "expected_salary": ("expected salary", "expected ctc", "salary expectation", "desired compensation"),
    "current_employer": ("current employer", "current company", "currently work"),
    "current_role": ("current role", "current title", "current designation", "job title"),
    "education": ("education", "qualification", "degree", "diploma"),
    "university": ("university", "college", "institution"),
    "graduation": ("graduation", "graduated", "year of passing"),
    "employment_type": ("employment type", "work arrangement", "job type"),
}
_EXCLUDED = re.compile(
    r"\b(?:bpo|insurance|healthcare|telesales|"
    r"medical|technical|industry|sector|specific domain)\b", re.I
)


@dataclass(frozen=True)
class LocalAnswer:
    answer: str = ""
    fact_key: str = ""
    state: str = "unresolved"


class LocalGroundedReasoner:
    def __init__(self, model: str, *, timeout_seconds: float = 3.0):
        name = str(model or "").strip()
        # Only a local model identifier, never a URL. Ollama uses local names.
        if not name or len(name) > 96 or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_.:/-]*", name
        ) or "://" in name:
            raise ValueError("invalid_local_model_name")
        self.model = name
        self.timeout = min(6.0, max(1.0, float(timeout_seconds)))

    @staticmethod
    def _normalized(value):
        return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).lower()).split())

    @classmethod
    def _scope_ok(cls, question: str, key: str) -> bool:
        q = cls._normalized(question)
        family = _FACT_FAMILIES[key]
        terms = _FAMILY_TERMS[family]
        if not any(token in q for token in terms):
            return False
        if family == "overall_experience":
            if _EXCLUDED.search(q):
                return False
            if any(term in q for term in (
                "customer success", "client success", "team management",
                "people management", "project management", "sales",
            )):
                return False
            if not any(term in q for term in ("overall", "total", "professional", "years of experience")):
                return False
            # Overall tenure cannot justify narrower technology, employer
            # or sector tenure (even if the question contains 'total').
            qualifiers = re.search(
                r"\\bexperience\\b.{0,65}\\b(?:with|using|for|on|in)\\s+([a-z]+)",
                q,
            )
            if qualifiers and qualifiers.group(1) not in (
                "total", "general", "all",
            ):
                return False
        if family == "customer_success_experience":
            if not any(term in q for term in ("customer success", "client success")):
                return False
        if family == "people_management_experience":
            if not any(term in q for term in ("people management", "team management", "managing people", "managing teams")):
                return False
        if family in ("current_salary", "expected_salary"):
            if family == "current_salary" and any(t in q for t in (
                "expect", "desired", "target", "want to earn",
            )):
                return False
            if family == "expected_salary" and any(t in q for t in (
                "current", "present", "last drawn",
            )):
                return False
        if family == "notice" and "shift" in q:
            return False
        return True

    def resolve(self, question: str, profile: Mapping, options: Sequence[str] = ()) -> LocalAnswer:
        from question_resolver import match_answer_to_option

        q = str(question or "").strip()
        if not 7 <= len(q) <= 450:
            return LocalAnswer(state="invalid_question")
        # Protected characteristics, specific jurisdictional/eligibility
        # claims, willingness, and yes/no thresholds are NEVER guessed here.
        # Existing deterministic resolvers and applicant prompts handle them.
        norm = self._normalized(q)
        # This mapper is ONLY for factual values/quantities. An interview
        # question, legal declaration or yes/no preference requires
        # applicant-approved evidence and cannot become a profile lookup.
        if norm.startswith(("why ", "describe ", "tell us ", "explain ",
                            "how would ", "what motivates ")):
            return LocalAnswer(state="subjective_question")
        if (norm.startswith((
                "do ", "does ", "did ", "is ", "are ", "will ",
                "would ", "could ", "can ", "have ", "has ",
            )) and not any(x in norm for x in (
                "how many", "number of days", "amount of",
            ))):
            return LocalAnswer(state="boolean_or_claim_not_provable")
        if re.search(r"\b(?:gender|race|sex|ethnicity|disability|veteran|"
                     r"citizenship|visa|sponsor|authorized|authorised|eligible|"
                     r"relocat|criminal|consent|agree|permission)\b", norm):
            return LocalAnswer(state="protected_or_eligibility")
        if "?" in q and re.search(
            r"\b(?:do you|are you|have you|would you|can you|will you)\b", norm
        ) and all(str(x).lower() in ("yes", "no", "true", "false") for x in options):
            return LocalAnswer(state="boolean_inference_forbidden")
        facts = {
            k: str(profile[k]).strip()
            for k in _FACT_FAMILIES if profile.get(k) not in (None, "")
            and type(profile.get(k)) in (str, int, float)
        }
        if not facts:
            return LocalAnswer(state="no_verified_fact")
        prompt = json.dumps({
            "task": "Choose the ONE applicant fact key that the employer question is explicitly requesting. "
                    "Never generate an answer, infer qualifications, or assume a missing fact. "
                    'Return ONLY JSON with a single field fact_key containing existing_key_or_NONE. '
                    "If the employer asks about a narrower domain, choose NONE.",
            "question": q,
            "available_fact_keys": list(facts),
            "fact_meanings": {k: _FACT_FAMILIES[k] for k in facts},
        }, ensure_ascii=False)
        try:
            body = json.dumps({
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            }).encode("utf-8")
            req = request.Request(
                _LOCAL_ENDPOINT, data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with request.urlopen(req, timeout=self.timeout) as response:
                if response.status != 200:
                    return LocalAnswer(state="model_unavailable")
                payload = json.load(response)
            if not isinstance(payload, dict) or not isinstance(payload.get("response"), str):
                return LocalAnswer(state="invalid_model_response")
            proposal = json.loads(payload["response"])
        except (error.URLError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return LocalAnswer(state="model_unavailable")
        if not isinstance(proposal, dict):
            return LocalAnswer(state="invalid_model_response")
        key = proposal.get("fact_key")
        if type(key) is not str or key not in facts or not self._scope_ok(q, key):
            return LocalAnswer(state="model_not_grounded")
        # The LLM has ZERO say in the answer. Only the exact fact value may
        # be returned; all possible UI options still need exact matching.
        fact_answer = facts[key]
        answer = match_answer_to_option(fact_answer, options)
        if options and not answer:
            return LocalAnswer(state="option_mismatch")
        return LocalAnswer(answer=answer or fact_answer,
                           fact_key=key, state="resolved")


_ACTIVE = None


def configure_local_reasoner(model: str = "") -> None:
    """Opt-in once for the current CLI process; empty disables."""
    global _ACTIVE
    _ACTIVE = LocalGroundedReasoner(model) if model else None


def resolve_with_local_reasoner(question: str, profile: Mapping,
                                options: Sequence[str] = ()) -> LocalAnswer:
    if _ACTIVE is None:
        return LocalAnswer(state="disabled")
    return _ACTIVE.resolve(question, profile, options)
