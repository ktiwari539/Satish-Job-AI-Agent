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


def evaluate_application_quota(
    policy: AutomationPolicy,
    store: JobStore,
    *,
    now: Optional[datetime] = None,
) -> QuotaStatus:
    """Evaluate whether another application may be attempted now.

    Only rows recorded as CONFIRMED are counted. Attempts, failures, blocked
    flows, and unverified submissions never consume a quota slot.
    """
    active = policy.active_window(now)
    bounds = policy.window_bounds(now)
    day_start, day_end = policy.operational_day_bounds(now)

    daily_confirmed = store.count_confirmed_submissions(
        start_utc=day_start,
        end_utc=day_end,
    )
    remaining_day = policy.remaining_for_day(daily_confirmed)

    if active is None or bounds is None:
        return QuotaStatus(
            allowed=False,
            reason="outside_application_window",
            daily_confirmed=daily_confirmed,
            remaining_day=remaining_day,
            operational_day_start=day_start.isoformat(),
            operational_day_end=day_end.isoformat(),
        )

    window_start, window_end = bounds
    window_confirmed = store.count_confirmed_submissions(
        start_utc=window_start,
        end_utc=window_end,
    )
    remaining_window = policy.remaining_for_window(window_confirmed, now)

    if remaining_day <= 0:
        reason = "daily_success_cap_reached"
        allowed = False
    elif remaining_window <= 0:
        reason = "window_success_target_reached"
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
    )
