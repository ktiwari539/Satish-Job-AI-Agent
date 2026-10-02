import csv
import sqlite3
from pathlib import Path

from dedupe import canonical_job_fingerprint
from models import Job, MatchResult, EligibilityResult


class JobStore:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_jobs (
                    job_key TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    company TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    canonical_key TEXT,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(seen_jobs)").fetchall()
            }
            if "canonical_key" not in columns:
                conn.execute("ALTER TABLE seen_jobs ADD COLUMN canonical_key TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_seen_jobs_canonical_key ON seen_jobs(canonical_key)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_seen_jobs_url ON seen_jobs(url)"
            )

    def is_seen(self, job: Job) -> bool:
        return self.is_duplicate(job)

    def is_duplicate(self, job: Job) -> bool:
        canonical = canonical_job_fingerprint(job)
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM seen_jobs
                WHERE job_key = ? OR url = ? OR canonical_key = ?
                LIMIT 1
                """,
                (job.key, job.url, canonical),
            ).fetchone()
        return row is not None

    def mark_seen(self, job: Job) -> None:
        canonical = canonical_job_fingerprint(job)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO seen_jobs(
                    job_key, source, company, title, url, canonical_key
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    job.key,
                    job.source,
                    job.company,
                    job.title,
                    job.url,
                    canonical,
                ),
            )


def append_audit(path: str, job: Job, match: MatchResult, eligibility: EligibilityResult, final_decision: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    exists = target.exists()
    with target.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "job_key", "source", "company", "title", "location", "url",
                "score", "role_score", "skill_score", "experience_score",
                "matched_skills", "missing_skills", "match_reasons",
                "match_decision", "eligible", "eligibility_reasons",
                "final_decision",
            ],
        )
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "job_key": job.key,
                "source": job.source,
                "company": job.company,
                "title": job.title,
                "location": job.location,
                "url": job.url,
                "score": match.score,
                "role_score": match.role_score,
                "skill_score": match.skill_score,
                "experience_score": match.experience_score,
                "matched_skills": "|".join(match.matched),
                "missing_skills": "|".join(match.missing),
                "match_reasons": "|".join(match.reasons),
                "match_decision": match.decision,
                "eligible": eligibility.eligible,
                "eligibility_reasons": "|".join(eligibility.reasons),
                "final_decision": final_decision,
            }
        )
