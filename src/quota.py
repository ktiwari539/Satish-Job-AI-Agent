from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from automation_policy import AutomationPolicy
from store import JobStore


@dataclass(frozen=True)
class QuotaStatus:
    allowed: bool
    reason: str
    active_window: str = ""
    window_confirmed: int = 0
    daily_confirmed: int = 0
    remaining_window: int = 0
    remaining_day: int = 0
    window_start: str = ""
    window_end: str = ""
    operational_day_start: str = ""
    operational_day_end: str = ""
    daily_reserved: int = 0
    window_reserved: int = 0


def evaluate_application_quota(
    policy: AutomationPolicy,
    store: JobStore,
    *,
    now: Optional[datetime] = None,
) -> QuotaStatus:
    """Evaluate whether another application may be attempted now.

    Only CONFIRMED rows count as success. Irreversible reservations hold
    capacity until reconciled; blocked work before reservation holds none.
    """
    active = policy.active_window(now)
    bounds = policy.window_bounds(now)
    day_start, day_end = policy.operational_day_bounds(now)

    capacity = store.submission_budget(policy, now=now)
    daily_confirmed = capacity['day']['confirmed']
    remaining_day = capacity['remaining_day']

    if active is None or bounds is None:
        return QuotaStatus(
            allowed=False,
            reason="outside_application_window",
            daily_confirmed=daily_confirmed,
            remaining_day=remaining_day,
            operational_day_start=day_start.isoformat(),
            operational_day_end=day_end.isoformat(),
            daily_reserved=capacity['day']['held'],
        )

    window_start, window_end = bounds
    window_confirmed = capacity['window']['confirmed']
    remaining_window = capacity['remaining_window']

    if remaining_day <= 0:
        reason = "daily_submission_capacity_reserved" if capacity['day']['held'] else "daily_success_cap_reached"
        allowed = False
    elif remaining_window <= 0:
        reason = "window_submission_capacity_reserved" if capacity['window']['held'] else "window_success_target_reached"
        allowed = False
    else:
        reason = "quota_available"
        allowed = True

    return QuotaStatus(
        allowed=allowed,
        reason=reason,
        active_window=active.key,
        window_confirmed=window_confirmed,
        daily_confirmed=daily_confirmed,
        remaining_window=remaining_window,
        remaining_day=remaining_day,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        operational_day_start=day_start.isoformat(),
        operational_day_end=day_end.isoformat(),
        daily_reserved=capacity['day']['held'],
        window_reserved=capacity['window']['held'],
    )
