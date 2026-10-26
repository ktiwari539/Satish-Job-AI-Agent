import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dedupe import (
    canonical_company,
    canonical_job_fingerprint,
    material_job_description_change,
    material_location_change,
    titles_similar,
)
from extractor import normalize_text
from models import Job, MatchResult, EligibilityResult
from application_exclusions import is_confirmed_exclusion


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    company TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    application_method TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    note TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(source, external_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_applications_url ON applications(url)"
            )
            application_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(applications)").fetchall()
            }
            if "location" not in application_columns:
                conn.execute("ALTER TABLE applications ADD COLUMN location TEXT NOT NULL DEFAULT ''")
            if "description" not in application_columns:
                conn.execute("ALTER TABLE applications ADD COLUMN description TEXT NOT NULL DEFAULT ''")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_applications_applied_at ON applications(applied_at)"
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS submission_attempts (
                source TEXT NOT NULL, external_id TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE, reserved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(source, external_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS preparation_attempts (
                source TEXT NOT NULL, external_id TEXT NOT NULL, url TEXT NOT NULL,
                profile_revision TEXT NOT NULL, state TEXT NOT NULL,
                checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(source, external_id)
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_preparation_attempts_url ON preparation_attempts(url)")

    def preparation_skip_reason(self, job: Job, revision: str, *, cooldown_hours: int = 24) -> str:
        """QA retry suppression, separate from confirmed-application dedupe."""
        if not revision or cooldown_hours <= 0:
            return ""
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("""SELECT state FROM preparation_attempts
                WHERE ((source=? AND external_id=?) OR url=?) AND profile_revision=?
                  AND checked_at >= datetime('now', ?) LIMIT 1""",
                (job.source, job.external_id, job.url, revision, f"-{int(cooldown_hours)} hours")).fetchone()
        if row is None:
            return ""
        return "recently_prepared_with_same_facts" if row[0] == "READY_FOR_REVIEW" else "recently_blocked_with_same_facts"

    def record_preparation_attempt(self, job: Job, revision: str, state: str) -> None:
        if not revision:
            return
        with sqlite3.connect(self.path) as conn:
            conn.execute("""INSERT INTO preparation_attempts(source,external_id,url,profile_revision,state)
                VALUES(?,?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET
                    url=excluded.url,profile_revision=excluded.profile_revision,state=excluded.state,
                    checked_at=CURRENT_TIMESTAMP""", (job.source,job.external_id,job.url,revision,state))

    def reserve_submission_attempt(self, job: Job) -> bool:
        """Durable, atomic single-click reservation, including uncertain outcomes.

        Commit BEFORE clicking. Crashes/timeouts must never permit an automatic
        retry. Reconciliation requires reviewing the exact portal job locally.
        """
        if is_confirmed_exclusion(job.source, job.external_id):
            return False
        with sqlite3.connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM applications WHERE (source=? AND external_id=?) OR url=?",
                            (job.source, job.external_id, job.url)).fetchone():
                return False
            cursor = conn.execute(
                "INSERT OR IGNORE INTO submission_attempts(source, external_id, url) VALUES(?,?,?)",
                (job.source, job.external_id, job.url),
            )
            return cursor.rowcount == 1

    def has_submission_attempt(self, job: Job) -> bool:
        with sqlite3.connect(self.path) as conn:
            return conn.execute(
                "SELECT 1 FROM submission_attempts WHERE (source=? AND external_id=?) OR url=?",
                (job.source, job.external_id, job.url),
            ).fetchone() is not None

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

    def mark_applied(
        self,
        job: Job,
        *,
        application_method: str = "manual",
        note: str = "",
    ) -> None:
        self.mark_seen(job)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO applications(
                    source, external_id, company, title, url,
                    status, application_method, note, location, description
                ) VALUES(?,?,?,?,?,'APPLIED',?,?,?,?)
                ON CONFLICT(source, external_id) DO UPDATE SET
                    company = excluded.company,
                    title = excluded.title,
                    url = excluded.url,
                    status = 'APPLIED',
                    application_method = excluded.application_method,
                    note = excluded.note,
                    location = excluded.location,
                    description = excluded.description,
                    applied_at = CURRENT_TIMESTAMP
                """,
                (
                    job.source,
                    job.external_id,
                    job.company,
                    job.title,
                    job.url,
                    application_method,
                    note,
                    job.location,
                    job.description,
                ),
            )

    def is_recent_similar_application(
        self,
        job: Job,
        *,
        cooldown_days: int = 90,
        allow_material_location_change: bool = True,
        allow_material_description_change: bool = True,
    ) -> bool:
        """Return True when a recent application is effectively the same role.

        Company suffixes and title seniority noise are normalized. A new job ID
        remains blocked during the cooldown unless there is positive evidence of
        a materially different location or a materially different full JD.
        Missing/short location or JD data never creates an exception.
        """
        # Exact previously applied jobs remain blocked beyond the similarity
        # cooldown, including manual LinkedIn reconciliation records.
        if (is_confirmed_exclusion(job.source, job.external_id)
                or self.is_applied(job) or self.has_submission_attempt(job)):
            return True
        if cooldown_days <= 0:
            return False

        company = canonical_company(job.company)

        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """
                SELECT company, title, location, description
                FROM applications
                WHERE applied_at >= datetime('now', ?)
                  AND status IN ('APPLIED', 'CONFIRMED')
                """,
                (f"-{int(cooldown_days)} days",),
            ).fetchall()

        for (
            previous_company,
            previous_title,
            previous_location,
            previous_description,
        ) in rows:
            if canonical_company(previous_company) != company:
                continue
            if not titles_similar(previous_title, job.title):
                continue

            if (
                allow_material_location_change
                and material_location_change(previous_location or "", job.location or "")
            ):
                continue

            if (
                allow_material_description_change
                and material_job_description_change(
                    previous_description or "",
                    job.description or "",
                )
            ):
                continue

            return True
        return False

    def mark_submission_confirmed(
        self,
        job: Job,
        *,
        application_method: str = "agent",
        note: str = "",
    ) -> None:
        """Record an application only after the portal confirmation is verified."""
        self.mark_seen(job)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO applications(
                    source, external_id, company, title, url,
                    status, application_method, note, location, description
                ) VALUES(?,?,?,?,?,'CONFIRMED',?,?,?,?)
                ON CONFLICT(source, external_id) DO UPDATE SET
                    company = excluded.company,
                    title = excluded.title,
                    url = excluded.url,
                    status = 'CONFIRMED',
                    application_method = excluded.application_method,
                    note = excluded.note,
                    location = excluded.location,
                    description = excluded.description,
                    applied_at = CURRENT_TIMESTAMP
                WHERE applications.status != 'CONFIRMED'
                   OR applications.application_method != excluded.application_method
                """,
                (
                    job.source,
                    job.external_id,
                    job.company,
                    job.title,
                    job.url,
                    application_method,
                    note,
                    job.location,
                    job.description,
                ),
            )

    def count_confirmed_submissions(
        self,
        *,
        start_utc: datetime,
        end_utc: datetime,
    ) -> int:
        if start_utc.tzinfo is None or end_utc.tzinfo is None:
            raise ValueError("start_utc and end_utc must be timezone-aware")
        start = start_utc.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        end = end_utc.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM applications
                WHERE status = 'CONFIRMED'
                  AND applied_at >= ?
                  AND applied_at < ?
                """,
                (start, end),
            ).fetchone()
        return int(row[0] if row else 0)

    def get_confirmed_submission(self, source: str, external_id: str):
        """Read back exact job's persisted confirmation without exposing its note.

        This is a local DB check, not an independent portal-side confirmation.
        Confirmation evidence must have been recorded by the submitter first.
        """
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT status, application_method, applied_at, note
                FROM applications
                WHERE source = ? AND external_id = ?
                LIMIT 1
                """,
                (source, external_id),
            ).fetchone()
        if not row or row[0] != "CONFIRMED" or row[1] != "agent" or not row[3]:
            return None
        return {"status": row[0], "application_method": row[1],
                "applied_at": row[2]}


    def is_applied(self, job: Job) -> bool:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM applications
                WHERE (source = ? AND external_id = ?) OR url = ?
                LIMIT 1
                """,
                (job.source, job.external_id, job.url),
            ).fetchone()
        return row is not None

    def is_applied_url(self, url: str) -> bool:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM applications
                WHERE url = ?
                LIMIT 1
                """,
                (url,),
            ).fetchone()
        return row is not None


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
