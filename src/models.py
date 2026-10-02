from dataclasses import dataclass, field


@dataclass(frozen=True)
class CandidateProfile:
    target_roles: tuple[str, ...]
    skills: tuple[str, ...]
    preferred_locations: tuple[str, ...]
    remote_allowed: bool
    total_experience_years: int
    india_authorized: bool
    outside_india_sponsorship_required: bool
    blocked_title_terms: tuple[str, ...] = field(default_factory=tuple)
    skill_taxonomy: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: dict) -> "CandidateProfile":
        skills = tuple(data.get("skills", ()))
        taxonomy = tuple(data.get("skill_taxonomy", ())) or skills
        return cls(
            target_roles=tuple(data.get("target_roles", ())),
            skills=skills,
            preferred_locations=tuple(data.get("preferred_locations", ())),
            remote_allowed=bool(data.get("remote_allowed", False)),
            total_experience_years=int(data.get("total_experience_years", 0)),
            india_authorized=bool(data.get("india_authorized", False)),
            outside_india_sponsorship_required=bool(
                data.get("outside_india_sponsorship_required", True)
            ),
            blocked_title_terms=tuple(data.get("blocked_title_terms", ())),
            skill_taxonomy=taxonomy,
        )


@dataclass(frozen=True)
class Job:
    source: str
    external_id: str
    company: str
    title: str
    location: str
    url: str
    description: str
    required_skills: tuple[str, ...] = field(default_factory=tuple)
    minimum_years: int | None = None
    remote: bool = False

    @property
    def key(self) -> str:
        return f"{self.source}:{self.company}:{self.external_id}"


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MatchResult:
    score: int
    decision: str
    matched: tuple[str, ...]
    missing: tuple[str, ...]
    role_score: int = 0
    skill_score: int = 0
    experience_score: int = 0
    reasons: tuple[str, ...] = field(default_factory=tuple)
