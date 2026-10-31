"""Launch a non-submitting local review worker with current Sheet controls.

Unattended discovery is limited to configured public Greenhouse/Lever feeds.
Registered browser portals are not an unattended-automation authorization.
"""
import fcntl
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone


PUBLIC_SOURCES = {'greenhouse': 'greenhouse_boards', 'lever': 'lever_sites'}


class ReviewConfigurationError(ValueError):
    pass


def build_review_command(environ, python=None):
    """Return fixed review-only arguments; never accepts submission flags."""
    portals = tuple(dict.fromkeys(p.strip().lower() for p in
        environ.get('JOB_AGENT_PORTALS', 'greenhouse,lever').split(',') if p.strip()))
    if not portals or any(p not in PUBLIC_SOURCES for p in portals):
        raise ReviewConfigurationError('scheduled_portal_requires_manual_or_authorized_workflow')
    try:
        maximum = int(environ.get('JOB_AGENT_MAX_JOBS', '10'))
    except ValueError:
        raise ReviewConfigurationError('scheduled_max_jobs_invalid') from None
    if not 1 <= maximum <= 20:
        raise ReviewConfigurationError('scheduled_max_jobs_invalid')
    sources_path = environ.get('JOB_AGENT_SOURCES', 'config/sources.example.json')
    try:
        path = Path(sources_path)
        if path.stat().st_size > 65536:
            raise ValueError('oversized')
        sources = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(sources, dict):
            raise ValueError('not_object')
        for portal in portals:
            targets = sources.get(PUBLIC_SOURCES[portal])
            if not isinstance(targets, list) or not targets or any(
                not isinstance(target, str) or not target.strip() for target in targets
            ):
                raise ValueError('missing_targets')
    except (OSError, ValueError, UnicodeError):
        raise ReviewConfigurationError('scheduled_public_sources_configuration_required') from None
    command = [python or sys.executable, 'src/certify_portals.py',
        '--portals', ','.join(portals), '--sources', sources_path,
        '--use-control-sheet', '--no-login', '--otp-mode', 'none',
        '--max-jobs', str(maximum), '--location', environ.get('JOB_AGENT_LOCATION', 'India'),
        '--report', 'data/certification/scheduled-review.json']
    if environ.get('JOB_AGENT_QUERY', '').strip():
        command.extend(['--query', environ['JOB_AGENT_QUERY']])
    return command


def acquire_run_lock(path):
    """Kernel lock survives exec and is released even after an abrupt exit."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None
    except BaseException:
        os.close(descriptor)
        raise
    # The review worker replaces this launcher, retaining the same lock.
    os.set_inheritable(descriptor, True)
    return descriptor


def emit_status(status, **fields):
    result = dict(status=status, at=datetime.now(timezone.utc).isoformat(),
        submission_enabled=False, submitted=0, confirmed=0, **fields)
    target = Path('data/certification/scheduled-review-launch.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf-8')
    os.replace(temporary, target)
    print(json.dumps(result, sort_keys=True), flush=True)


def main():
    try:
        descriptor = acquire_run_lock('data/review-worker.lock')
    except OSError:
        print(json.dumps(dict(status='scheduled_review_lock_unavailable',
            submitted=0, confirmed=0)), flush=True)
        return 2
    if descriptor is None:
        # Leave the active worker's launch report intact.
        print(json.dumps(dict(status='scheduled_review_already_running',
            submitted=0, confirmed=0)), flush=True)
        return 0
    try:
        try:
            command = build_review_command(os.environ)
        except ReviewConfigurationError as exc:
            emit_status('scheduled_review_configuration_required', reason_code=str(exc))
            return 2
        emit_status('scheduled_review_started')
        try:
            os.execv(command[0], command)
        except OSError:
            emit_status('scheduled_review_launch_failed', reason_code='worker_exec_failed')
            return 2
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    raise SystemExit(main())
