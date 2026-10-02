import csv
import sqlite3
from pathlib import Path

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
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def is_seen(self, job: Job) -> bool:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT 1 FROM seen_jobs WHERE job_key = ?", (job.key,)).fetchone()
        return row is not None

    def mark_seen(self, job: Job) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seen_jobs(job_key, source, company, title, url) VALUES(?,?,?,?,?)",
                (job.key, job.source, job.company, job.title, job.url),
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
                "score", "match_decision", "eligible", "eligibility_reasons",
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
                "match_decision": match.decision,
                "eligible": eligibility.eligible,
                "eligibility_reasons": "|".join(eligibility.reasons),
                "final_decision": final_decision,
            }
        )
