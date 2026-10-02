import json
from pathlib import Path
from typing import Iterable

from matcher import score_profile
from models import CandidateProfile, Job
from policy import evaluate_eligibility
from sources import discover_greenhouse, discover_lever
from store import JobStore, append_audit


def load_profile(path: str) -> CandidateProfile:
    return CandidateProfile.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def discover_from_config(path: str, taxonomy: tuple[str, ...]) -> list[Job]:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    jobs: list[Job] = []
    for board in config.get("greenhouse_boards", []):
        jobs.extend(discover_greenhouse(board, taxonomy))
    for site in config.get("lever_sites", []):
        jobs.extend(discover_lever(site, taxonomy))
    return jobs


def evaluate_jobs(
    jobs: Iterable[Job],
    profile: CandidateProfile,
    threshold: int,
    store: JobStore,
    audit_path: str,
) -> dict[str, int]:
    summary = {"discovered": 0, "new": 0, "qualified": 0, "skipped": 0, "duplicates": 0}
    for job in jobs:
        summary["discovered"] += 1
        if store.is_duplicate(job):
            summary["duplicates"] += 1
            continue

        summary["new"] += 1
        match = score_profile(profile, job, threshold=threshold)
        eligibility = evaluate_eligibility(profile, job)
        final_decision = "QUALIFIED_DRY_RUN" if match.decision == "APPLY" and eligibility.eligible else "SKIP"
        if final_decision == "QUALIFIED_DRY_RUN":
            summary["qualified"] += 1
        else:
            summary["skipped"] += 1

        append_audit(audit_path, job, match, eligibility, final_decision)
        store.mark_seen(job)
    return summary
