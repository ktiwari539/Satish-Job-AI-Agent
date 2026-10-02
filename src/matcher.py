from typing import Iterable, Set

from models import CandidateProfile, Job, MatchResult


def _norm(values: Iterable[str]) -> Set[str]:
    return {v.strip().lower() for v in values if v and v.strip()}


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


def _role_score(target_roles: Iterable[str], title: str) -> int:
    title_norm = title.strip().lower()
    roles = _norm(target_roles)
    if not title_norm or not roles:
        return 0
    if any(role in title_norm for role in roles):
        return 100

    title_tokens = set(title_norm.replace("/", " ").replace("-", " ").split())
    best = 0
    for role in roles:
        role_tokens = set(role.replace("/", " ").replace("-", " ").split())
        if role_tokens:
            best = max(best, round(len(title_tokens & role_tokens) / len(role_tokens) * 100))
    return best


def score_profile(profile: CandidateProfile, job: Job, threshold: int = 75) -> MatchResult:
    candidate = _norm(profile.skills)
    required = _norm(job.required_skills)
    matched = tuple(sorted(candidate & required))
    missing = tuple(sorted(required - candidate))

    skill_score = round(len(matched) / len(required) * 100) if required else 50
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

    weighted = round(skill_score * 0.50 + role_score * 0.30 + experience_score * 0.20)
    reasons = (
        f"skill={skill_score}",
        f"role={role_score}",
        f"experience={experience_score}",
    )
    decision = "APPLY" if weighted >= threshold else "SKIP"
    return MatchResult(
        score=weighted,
        decision=decision,
        matched=matched,
        missing=missing,
        role_score=role_score,
        skill_score=skill_score,
        experience_score=experience_score,
        reasons=reasons,
    )
