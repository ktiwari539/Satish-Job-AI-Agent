from typing import Iterable, Optional, Set

from extractor import normalize_text
from models import CandidateProfile, Job, MatchResult


SENIORITY_WORDS = {
    "senior", "sr", "lead", "manager", "head", "director", "principal",
    "specialist", "associate", "technical",
}


def _norm(values: Iterable[str]) -> Set[str]:
    return {normalize_text(v) for v in values if v and normalize_text(v)}


def score_job(candidate_skills: Iterable[str], required_skills: Iterable[str], threshold: int = 75) -> MatchResult:
    candidate = _norm(candidate_skills)
    required = _norm(required_skills)

    if not required:
        return MatchResult(score=0, decision="SKIP", matched=(), missing=())

    matched = tuple(sorted(candidate & required))
    missing = tuple(sorted(required - candidate))
    score = round((len(matched) / len(required)) * 100)
    decision = "APPLY" if score >= threshold else "SKIP"

    return MatchResult(
        score=score,
        decision=decision,
        matched=matched,
        missing=missing,
        skill_score=score,
    )


def _content_tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_text(value).replace("/", " ").replace("-", " ").split()
        if token not in SENIORITY_WORDS and len(token) > 2
    }


def _role_score(target_roles: Iterable[str], title: str) -> int:
    title_norm = normalize_text(title)
    roles = _norm(target_roles)
    if not title_norm or not roles:
        return 0

    if any(role in title_norm for role in roles):
        return 100

    title_tokens = _content_tokens(title_norm)
    if not title_tokens:
        return 0

    best = 0
    for role in roles:
        role_tokens = _content_tokens(role)
        if not role_tokens:
            continue
        overlap = len(title_tokens & role_tokens)
        recall = overlap / len(role_tokens)
        precision = overlap / len(title_tokens)
        best = max(best, round((recall * 0.7 + precision * 0.3) * 100))
    return best


def _blocked_title(profile: CandidateProfile, title: str) -> Optional[str]:
    title_norm = normalize_text(title)
    for blocked in profile.blocked_title_terms:
        blocked_norm = normalize_text(blocked)
        if blocked_norm and blocked_norm in title_norm:
            return blocked_norm
    return None


def score_profile(profile: CandidateProfile, job: Job, threshold: int = 75) -> MatchResult:
    candidate = _norm(profile.skills)
    required = _norm(job.required_skills)
    matched = tuple(sorted(candidate & required))
    missing = tuple(sorted(required - candidate))

    if required:
        skill_score = round(len(matched) / len(required) * 100)
        if len(required) < 3:
            skill_score = min(skill_score, 75)
    else:
        skill_score = 45

    role_score = _role_score(profile.target_roles, job.title)

    if job.minimum_years is None:
        experience_score = 80
    elif profile.total_experience_years >= job.minimum_years:
        experience_score = 100
    else:
        experience_score = max(
            0,
            round(profile.total_experience_years / max(job.minimum_years, 1) * 100),
        )

    weighted = round(skill_score * 0.35 + role_score * 0.45 + experience_score * 0.20)
    reasons = [
        f"skill={skill_score}",
        f"role={role_score}",
        f"experience={experience_score}",
    ]

    blocked = _blocked_title(profile, job.title)
    if blocked:
        reasons.append(f"blocked_title={blocked}")

    role_gate_failed = role_score < 55
    if role_gate_failed:
        reasons.append("role_gate<55")

    decision = (
        "APPLY"
        if weighted >= threshold and not blocked and not role_gate_failed
        else "SKIP"
    )

    return MatchResult(
        score=weighted,
        decision=decision,
        matched=matched,
        missing=missing,
        role_score=role_score,
        skill_score=skill_score,
        experience_score=experience_score,
        reasons=tuple(reasons),
    )
