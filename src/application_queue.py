"""Durable, leased preparation queue sharing the application's SQLite ledger.

This module never opens a browser, stores applicant answers, or clicks Submit.
Only the existing submission guard may create an irreversible reservation.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
import secrets
import sqlite3
import time
from urllib.parse import parse_qs, urlsplit, urlunsplit

from application_exclusions import is_confirmed_exclusion
from dedupe import canonical_company, titles_similar, material_location_change, material_job_description_change
from models import Job


STATES = ('QUEUED', 'PREPARING', 'ELIGIBLE', 'PREPARED', 'NEEDS_INPUT',
          'RETRY_WAIT', 'SKIPPED', 'SUBMISSION_RESERVED', 'SUBMISSION_UNCERTAIN', 'CONFIRMED')
OWNED_STATES = ('PREPARING', 'ELIGIBLE')
TERMINAL_SUBMISSION_STATES = ('SUBMISSION_RESERVED', 'SUBMISSION_UNCERTAIN', 'CONFIRMED')


class QueueError(ValueError):
    pass


def reason_code(value):
    """Persist a bounded category, never arbitrary exception/question text."""
    return value if isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,79}', value) else 'job_requires_review'


def canonical_queue_job(job):
    if not isinstance(job, Job):
        raise QueueError('invalid_queue_job')
    for key, limit in (('source', 30), ('external_id', 150), ('company', 300),
                       ('title', 300), ('location', 300), ('description', 25000), ('url', 4000)):
        value = getattr(job, key)
        if not isinstance(value, str) or len(value) > limit:
            raise QueueError('invalid_queue_job')
    if not job.external_id.strip() or not job.title.strip() or not job.company.strip():
        raise QueueError('queue_job_identity_missing')
    if type(job.remote) is not bool or (job.minimum_years is not None and
            (type(job.minimum_years) is not int or not 0 <= job.minimum_years <= 80)):
        raise QueueError('invalid_queue_job')
    if not isinstance(job.required_skills, (tuple, list)) or len(job.required_skills) > 150 or any(
            not isinstance(skill, str) or len(skill) > 200 for skill in job.required_skills):
        raise QueueError('invalid_queue_job')
    try:
        parsed = urlsplit(job.url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError()
        host = (parsed.hostname or '').lower()
        query = parse_qs(parsed.query,keep_blank_values=True)
        if job.source == 'linkedin':
            from linkedin_exact_job import parse_linkedin_target
            target = parse_linkedin_target(job.url)
            if target.job_id != job.external_id: raise ValueError()
            if 'currentJobId' in query and query['currentJobId'] != [job.external_id]: raise ValueError()
            url = target.url
        elif job.source in ('naukri', 'indeed'):
            from portal_export_urls import canonical_export_job_url
            url = canonical_export_job_url(job.source, job.url)
            if not url: raise ValueError()
            if job.source == 'indeed' and parse_qs(urlsplit(url).query).get('jk') != [job.external_id]:
                raise ValueError()
        elif job.source == 'greenhouse':
            match = re.fullmatch(r'/[^/]+/jobs/([0-9]+)/?', parsed.path)
            if host not in ('boards.greenhouse.io', 'job-boards.greenhouse.io', 'boards.eu.greenhouse.io', 'job-boards.eu.greenhouse.io') or not match or match[1] != job.external_id:
                raise ValueError()
            if 'gh_jid' in query and query['gh_jid'] != [job.external_id]: raise ValueError()
            url = urlunsplit(('https', host, parsed.path.rstrip('/'), '', ''))
        elif job.source == 'lever':
            match = re.fullmatch(r'/[^/]+/([a-zA-Z0-9-]+)(?:/apply)?/?', parsed.path)
            if host not in ('jobs.lever.co', 'jobs.eu.lever.co') or not match or match[1] != job.external_id:
                raise ValueError()
            url = 'https://' + host + '/' + parsed.path.strip('/').removesuffix('/apply')
        else:
            raise QueueError('unsupported_queue_portal')
    except QueueError:
        raise
    except (ValueError, TypeError, AttributeError):
        raise QueueError('queue_job_url_identity_invalid') from None
    return replace(job, url=url, required_skills=tuple(job.required_skills))


def same_role(left, right):
    return (canonical_company(left.company) and canonical_company(left.company) == canonical_company(right.company)
            and titles_similar(left.title, right.title)
            and not material_location_change(left.location, right.location)
            and not material_job_description_change(left.description, right.description))


def verified_preparation(evidence):
    e = evidence or {}
    return (e.get('flow_state') in ('REVIEW_INSPECTED','SUBMIT_READY')
            and all(e.get(key) is True for key in ('exact_job_verified', 'form_exercised', 'identity_verified', 'submit_control_verified'))
            and e.get('resume_evidence_state') == 'matching_resume_selected'
            and type(e.get('unknown_required_count')) is int and e['unknown_required_count'] == 0
            and type(e.get('review_mismatch_count')) is int and e['review_mismatch_count'] == 0
            and e.get('submission_enabled') is False and type(e.get('submitted')) is int and e['submitted'] == 0
            and type(e.get('confirmed')) is int and e['confirmed'] == 0)


@dataclass(frozen=True)
class QueueLease:
    id: int
    token: str
    job: Job
    facts_revision: str
    attempts: int


class ApplicationQueue:
    def __init__(self, store, *, clock=time.time):
        self.store = store
        self.path = store.path
        self.clock = clock
        with self.transaction() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS agent_queue_control (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    paused INTEGER NOT NULL DEFAULT 0 CHECK(paused IN (0,1)));
                INSERT OR IGNORE INTO agent_queue_control(singleton) VALUES(1);
                CREATE TABLE IF NOT EXISTS agent_queue_jobs (
                    id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE, job_json TEXT NOT NULL, facts_revision TEXT NOT NULL,
                    state TEXT NOT NULL, reason_code TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0,
                    lease_hash TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(source,external_id));
                CREATE INDEX IF NOT EXISTS agent_queue_claim ON agent_queue_jobs(state,available_at,id);
                CREATE TABLE IF NOT EXISTS agent_queue_events (
                    id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL, state TEXT NOT NULL,
                    reason_code TEXT NOT NULL, at REAL NOT NULL);
            ''')

    @contextmanager
    def transaction(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _event(self, conn, job_id, state, reason=''):
        conn.execute('INSERT INTO agent_queue_events(job_id,state,reason_code,at) VALUES(?,?,?,?)',
                     (job_id, state, reason_code(reason) if reason else '', self.clock()))

    def _state(self, conn, row, state, reason=''):
        conn.execute('''UPDATE agent_queue_jobs SET state=?,reason_code=?,updated_at=?,
            lease_hash='',lease_until=0 WHERE id=?''', (state, reason, self.clock(), row['id']))
        self._event(conn, row['id'], state, reason)

    def _ledger_state(self, conn, job):
        if is_confirmed_exclusion(job.source, job.external_id):
            return 'SKIPPED', 'confirmed_manual_application_exclusion'
        applied = conn.execute('SELECT status FROM applications WHERE (source=? AND external_id=?) OR url=? LIMIT 1',
                               (job.source, job.external_id, job.url)).fetchone()
        if applied:
            return ('CONFIRMED', 'ledger_confirmation') if applied['status'] == 'CONFIRMED' else ('SKIPPED', 'already_applied')
        if conn.execute('SELECT 1 FROM submission_attempts WHERE (source=? AND external_id=?) OR url=?',
                        (job.source, job.external_id, job.url)).fetchone():
            return 'SUBMISSION_UNCERTAIN', 'submission_reconciliation_required'
        return None

    def enqueue(self, job, facts_revision):
        return self.enqueue_many([job], facts_revision)[0]

    def enqueue_many(self, jobs, facts_revision):
        jobs = [canonical_queue_job(job) for job in jobs]
        if not isinstance(facts_revision, str) or not re.fullmatch(r'[a-f0-9]{64}', facts_revision):
            raise QueueError('invalid_facts_revision')
        with self.transaction() as conn:
            self._recover(conn)
            return [self._enqueue(conn, job, facts_revision) for job in jobs]

    def _enqueue(self, conn, job, facts_revision):
        now = self.clock()
        row = conn.execute('SELECT * FROM agent_queue_jobs WHERE (source=? AND external_id=?) OR url=?',
                           (job.source, job.external_id, job.url)).fetchone()
        if row and (row['source'] != job.source or row['external_id'] != job.external_id or row['url'] != job.url):
            raise QueueError('queue_job_identity_changed')
        if not row:
            cursor = conn.execute('''INSERT INTO agent_queue_jobs
                (source,external_id,url,job_json,facts_revision,state,created_at,updated_at)
                VALUES(?,?,?,?,?,'QUEUED',?,?)''',
                (job.source, job.external_id, job.url, json.dumps(asdict(job), sort_keys=True), facts_revision, now, now))
            row = conn.execute('SELECT * FROM agent_queue_jobs WHERE id=?', (cursor.lastrowid,)).fetchone()
            self._event(conn, row['id'], 'QUEUED')
        ledger = self._ledger_state(conn, job)
        if ledger:
            if row['state'] != ledger[0]: self._state(conn, row, *ledger)
        elif row['state'] not in OWNED_STATES + TERMINAL_SUBMISSION_STATES:
            old = Job(**json.loads(row['job_json']))
            # A search snippet cannot erase a verified full JD or continually
            # invalidate the same blocked/prepared posting on every discovery.
            if len(job.description.strip()) < 200 and len(old.description.strip()) >= 200:
                job = replace(job,description=old.description,required_skills=old.required_skills,
                              minimum_years=old.minimum_years,remote=old.remote)
            if not job.location.strip(): job = replace(job,location=old.location)
            payload = json.dumps(asdict(job), sort_keys=True)
            if row['facts_revision'] != facts_revision or row['job_json'] != payload:
                conn.execute('''UPDATE agent_queue_jobs SET job_json=?,facts_revision=?,attempts=0,
                    available_at=0 WHERE id=?''', (payload, facts_revision, row['id']))
                self._state(conn, row, 'QUEUED', 'preparation_inputs_changed')
        return row['id']

    def paused(self):
        with self.transaction() as conn:
            return bool(conn.execute('SELECT paused FROM agent_queue_control WHERE singleton=1').fetchone()[0])

    def set_paused(self, paused):
        if type(paused) is not bool: raise QueueError('invalid_pause_value')
        with self.transaction() as conn:
            conn.execute('UPDATE agent_queue_control SET paused=? WHERE singleton=1', (int(paused),))

    def refresh_revision(self, revision, sources):
        """A trusted worker revalidates stored jobs against its current inputs."""
        if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{64}', revision):
            raise QueueError('invalid_facts_revision')
        with self.transaction() as conn:
            self._recover(conn)
            for row in conn.execute('SELECT * FROM agent_queue_jobs WHERE facts_revision!=?', (revision,)).fetchall():
                if row['source'] in sources and row['state'] not in OWNED_STATES + TERMINAL_SUBMISSION_STATES:
                    conn.execute('UPDATE agent_queue_jobs SET facts_revision=?,attempts=0,available_at=0 WHERE id=?', (revision,row['id']))
                    self._state(conn, row, 'QUEUED', 'preparation_inputs_changed')

    def _recover(self, conn):
        now = self.clock()
        for row in conn.execute("SELECT * FROM agent_queue_jobs WHERE state NOT IN ('CONFIRMED','SKIPPED')").fetchall():
            job = Job(**json.loads(row['job_json']))
            ledger = self._ledger_state(conn, job)
            if ledger:
                self._state(conn, row, *ledger)
            elif row['state'] == 'SUBMISSION_RESERVED':
                self._state(conn, row, 'SUBMISSION_UNCERTAIN', 'submission_reconciliation_required')
            elif row['state'] in OWNED_STATES and row['lease_until'] <= now:
                self._state(conn, row, 'QUEUED' if row['attempts'] < 3 else 'NEEDS_INPUT',
                            'preparation_lease_expired' if row['attempts'] < 3 else 'preparation_retry_limit_reached')

    def claim(self, *, sources, lease_seconds=900):
        if not isinstance(sources, (list, tuple)) or not sources or any(
                source not in ('linkedin', 'indeed', 'naukri', 'greenhouse', 'lever') for source in sources):
            raise QueueError('invalid_queue_sources')
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise QueueError('invalid_lease_duration')
        with self.transaction() as conn:
            self._recover(conn)
            if conn.execute('SELECT paused FROM agent_queue_control WHERE singleton=1').fetchone()[0]: return None
            placeholders = ','.join('?' for _ in sources)
            candidates = conn.execute("SELECT * FROM agent_queue_jobs WHERE state IN ('QUEUED','RETRY_WAIT') "
                'AND available_at<=? AND source IN (' + placeholders + ') ORDER BY id', (self.clock(), *sources)).fetchall()
            for row in candidates:
                job = Job(**json.loads(row['job_json']))
                ledger = self._ledger_state(conn, job)
                if ledger:
                    self._state(conn, row, *ledger)
                    continue
                previous = conn.execute("SELECT job_json FROM agent_queue_jobs WHERE id!=? AND state IN "
                    "('PREPARING','ELIGIBLE','PREPARED','SUBMISSION_RESERVED','SUBMISSION_UNCERTAIN','CONFIRMED')",
                    (row['id'],)).fetchall()
                if any(same_role(Job(**json.loads(other['job_json'])), job) for other in previous):
                    self._state(conn, row, 'SKIPPED', 'same_role_already_in_queue')
                    continue
                token = secrets.token_urlsafe(32)
                conn.execute("UPDATE agent_queue_jobs SET state='PREPARING',attempts=attempts+1,lease_hash=?,"
                    "lease_until=?,updated_at=? WHERE id=?", (hashlib.sha256(token.encode()).hexdigest(),
                    self.clock()+lease_seconds, self.clock(), row['id']))
                self._event(conn, row['id'], 'PREPARING')
                return QueueLease(row['id'], token, job, row['facts_revision'], row['attempts']+1)
        return None

    def _owned(self, conn, lease):
        row = conn.execute('SELECT * FROM agent_queue_jobs WHERE id=?', (lease.id,)).fetchone()
        if not row or row['state'] not in OWNED_STATES or row['lease_until'] <= self.clock() or not secrets.compare_digest(
                row['lease_hash'], hashlib.sha256(lease.token.encode()).hexdigest()):
            raise QueueError('stale_preparation_lease')
        return row

    def eligible(self, lease, job):
        job = canonical_queue_job(job)
        with self.transaction() as conn:
            row = self._owned(conn, lease)
            if (job.source, job.external_id, job.url) != (row['source'], row['external_id'], row['url']):
                raise QueueError('queue_job_identity_changed')
            conn.execute("UPDATE agent_queue_jobs SET state='ELIGIBLE',job_json=?,updated_at=? WHERE id=?",
                         (json.dumps(asdict(job), sort_keys=True), self.clock(), row['id']))
            self._event(conn, row['id'], 'ELIGIBLE')

    def finish(self, lease, state, reason='', *, evidence=None):
        if state not in ('PREPARED', 'NEEDS_INPUT', 'SKIPPED', 'RETRY_WAIT'):
            raise QueueError('invalid_preparation_transition')
        reason = reason_code(reason) if reason else ''
        if state == 'PREPARED':
            if not verified_preparation(evidence):
                raise QueueError('preparation_evidence_incomplete')
        with self.transaction() as conn:
            row = self._owned(conn, lease)
            if state == 'PREPARED' and row['state'] != 'ELIGIBLE': raise QueueError('eligibility_required')
            if state == 'RETRY_WAIT' and row['attempts'] >= 3:
                state, reason = 'NEEDS_INPUT', 'preparation_retry_limit_reached'
            self._state(conn, row, state, reason)
            if state == 'RETRY_WAIT':
                conn.execute('UPDATE agent_queue_jobs SET available_at=? WHERE id=?', (self.clock()+60, row['id']))

    def defer(self, lease, reason):
        """Pause/control changes before a form do not use a retry attempt."""
        with self.transaction() as conn:
            row = self._owned(conn, lease)
            self._state(conn, row, 'QUEUED', reason_code(reason))
            conn.execute('UPDATE agent_queue_jobs SET attempts=MAX(attempts-1,0),available_at=0 WHERE id=?', (row['id'],))

    def snapshot(self, *, limit=50, state=None):
        if type(limit) is not int or not 1 <= limit <= 100 or (state is not None and state not in STATES):
            raise QueueError('invalid_queue_query')
        with self.transaction() as conn:
            self._recover(conn)
            counts = {key: 0 for key in STATES}
            counts.update({row['state']: row['n'] for row in conn.execute('SELECT state,COUNT(*) n FROM agent_queue_jobs GROUP BY state')})
            rows = conn.execute('SELECT * FROM agent_queue_jobs ' + ('WHERE state=? ' if state else '') + 'ORDER BY id LIMIT ?',
                                (state, limit) if state else (limit,)).fetchall()
            items = []
            for row in rows:
                job = json.loads(row['job_json'])
                items.append(dict(id=row['id'], source=row['source'], external_id=row['external_id'], url=row['url'],
                    company=job['company'], title=job['title'], state=row['state'], reason_code=row['reason_code'],
                    attempts=row['attempts'], updated_at=row['updated_at']))
            return dict(paused=bool(conn.execute('SELECT paused FROM agent_queue_control WHERE singleton=1').fetchone()[0]),
                        counts=counts, jobs=items, submission_enabled=False)
