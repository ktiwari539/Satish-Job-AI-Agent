"""Submission capacity: successes are counted, unresolved attempts hold slots."""
from datetime import datetime, timezone


def utc_sql(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('submission_period_requires_aware_datetime')
    return value.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def usage(conn, start, end):
    bounds = (utc_sql(start), utc_sql(end))
    confirmed = conn.execute("SELECT COUNT(*) FROM applications WHERE status='CONFIRMED' AND applied_at>=? AND applied_at<?", bounds).fetchone()[0]
    held = conn.execute('''SELECT COUNT(*) FROM submission_attempts a
        WHERE reserved_at>=? AND reserved_at<? AND NOT EXISTS
        (SELECT 1 FROM applications p WHERE (p.source=a.source AND p.external_id=a.external_id) OR p.url=a.url)''', bounds).fetchone()[0]
    return dict(confirmed=confirmed, held=held, used=confirmed+held)


def budget(conn, policy, now=None):
    day = usage(conn, *policy.operational_day_bounds(now))
    bounds = policy.window_bounds(now)
    window = usage(conn, *bounds) if bounds else dict(confirmed=0, held=0, used=0)
    active = policy.active_window(now)
    return dict(day=day, window=window, daily_cap=policy.daily_success_cap,
                remaining_day=max(0, policy.daily_success_cap-day['used']),
                remaining_window=max(0, active.target_successes-window['used']) if active else 0,
                inside_window=active is not None)
