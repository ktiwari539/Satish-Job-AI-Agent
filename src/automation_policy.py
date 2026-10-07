from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ApplicationWindow:
    key: str
    start: time
    end: time
    target_successes: int

    @property
    def crosses_midnight(self) -> bool:
        return self.end <= self.start

    def contains(self, local_dt: datetime) -> bool:
        current = local_dt.timetz().replace(tzinfo=None)
        if not self.crosses_midnight:
            return self.start <= current < self.end
        return current >= self.start or current < self.end


@dataclass(frozen=True)
class AutomationPolicy:
    timezone: str
    threshold: int
    daily_success_cap: int
    count_only_confirmed_submissions: bool
    stop_at_window_end: bool
    windows: tuple[ApplicationWindow, ...]
    sign_in_if_needed: bool
    create_account_if_missing: bool
    reuse_email_across_portals: bool
    allow_configured_password_reuse: bool
    credentials_source: str
    duplicate_cooldown_days: int

    def active_window(self, now: Optional[datetime] = None) -> Optional[ApplicationWindow]:
        tz = ZoneInfo(self.timezone)
        local_now = (now or datetime.now(tz))
        if local_now.tzinfo is None:
            local_now = local_now.replace(tzinfo=tz)
        else:
            local_now = local_now.astimezone(tz)
        for window in self.windows:
            if window.contains(local_now):
                return window
        return None

    def remaining_for_window(self, successful_submissions: int, now: Optional[datetime] = None) -> int:
        window = self.active_window(now)
        if window is None:
            return 0
        return max(window.target_successes - max(successful_submissions, 0), 0)

    def remaining_for_day(self, successful_submissions: int) -> int:
        return max(self.daily_success_cap - max(successful_submissions, 0), 0)


def _parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def load_automation_policy(path: str) -> AutomationPolicy:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    schedule = data["schedule"]
    auth = data["authentication"]
    duplicate = data["duplicate_policy"]

    windows = tuple(
        ApplicationWindow(
            key=item["key"],
            start=_parse_time(item["start"]),
            end=_parse_time(item["end"]),
            target_successes=int(item["target_successes"]),
        )
        for item in schedule["windows"]
    )

    return AutomationPolicy(
        timezone=schedule["timezone"],
        threshold=int(data["application"]["auto_submit_threshold"]),
        daily_success_cap=int(schedule["daily_success_cap"]),
        count_only_confirmed_submissions=bool(schedule["count_only_confirmed_submissions"]),
        stop_at_window_end=bool(schedule["stop_at_window_end"]),
        windows=windows,
        sign_in_if_needed=bool(auth["sign_in_if_needed"]),
        create_account_if_missing=bool(auth["create_account_if_missing"]),
        reuse_email_across_portals=bool(auth["reuse_email_across_portals"]),
        allow_configured_password_reuse=bool(auth["allow_configured_password_reuse"]),
        credentials_source=str(auth["credentials_source"]),
        duplicate_cooldown_days=int(duplicate["same_company_similar_role_cooldown_days"]),
    )
