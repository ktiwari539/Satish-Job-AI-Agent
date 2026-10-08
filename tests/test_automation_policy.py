import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from automation_policy import load_automation_policy


class AutomationPolicyTests(unittest.TestCase):
    def _policy(self):
        payload = {
            "application": {"auto_submit_threshold": 75},
            "schedule": {
                "timezone": "Asia/Kolkata",
                "daily_success_cap": 100,
                "count_only_confirmed_submissions": True,
                "stop_at_window_end": True,
                "windows": [
                    {"key": "morning", "start": "10:00", "end": "12:00", "target_successes": 50},
                    {"key": "night", "start": "23:00", "end": "01:00", "target_successes": 50},
                ],
            },
            "authentication": {
                "sign_in_if_needed": True,
                "create_account_if_missing": True,
                "reuse_email_across_portals": True,
                "allow_configured_password_reuse": True,
                "credentials_source": "local_secret_only",
            },
            "duplicate_policy": {
                "same_company_similar_role_cooldown_days": 90,
            },
        }
        temp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        try:
            json.dump(payload, temp)
            temp.close()
            return load_automation_policy(temp.name)
        finally:
            Path(temp.name).unlink(missing_ok=True)

    def test_morning_window_targets_50(self):
        policy = self._policy()
        now = datetime(2026, 10, 7, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
        window = policy.active_window(now)
        self.assertIsNotNone(window)
        self.assertEqual(window.key, "morning")
        self.assertEqual(window.target_successes, 50)
        self.assertEqual(policy.remaining_for_window(12, now), 38)

    def test_cross_midnight_night_window(self):
        policy = self._policy()
        before_midnight = datetime(2026, 10, 7, 23, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
        after_midnight = datetime(2026, 10, 8, 0, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
        self.assertEqual(policy.active_window(before_midnight).key, "night")
        self.assertEqual(policy.active_window(after_midnight).key, "night")

    def test_night_window_bounds_anchor_to_previous_date_after_midnight(self):
        policy = self._policy()
        now = datetime(2026, 10, 8, 0, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
        start, end = policy.window_bounds(now)
        self.assertEqual(start.isoformat(), "2026-10-07T23:00:00+05:30")
        self.assertEqual(end.isoformat(), "2026-10-08T01:00:00+05:30")

    def test_operational_day_keeps_morning_and_night_in_same_daily_cap(self):
        policy = self._policy()
        morning = datetime(2026, 10, 7, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
        after_midnight = datetime(2026, 10, 8, 0, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
        morning_bounds = policy.operational_day_bounds(morning)
        night_bounds = policy.operational_day_bounds(after_midnight)
        self.assertEqual(morning_bounds, night_bounds)
        self.assertEqual(morning_bounds[0].isoformat(), "2026-10-07T10:00:00+05:30")
        self.assertEqual(morning_bounds[1].isoformat(), "2026-10-08T10:00:00+05:30")

    def test_outside_windows_returns_none(self):
        policy = self._policy()
        now = datetime(2026, 10, 7, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        self.assertIsNone(policy.active_window(now))
        self.assertEqual(policy.remaining_for_window(0, now), 0)

    def test_daily_cap_is_100_confirmed_submissions(self):
        policy = self._policy()
        self.assertEqual(policy.daily_success_cap, 100)
        self.assertTrue(policy.count_only_confirmed_submissions)
        self.assertEqual(policy.remaining_for_day(73), 27)

    def test_auth_policy_allows_login_and_signup_from_local_secret(self):
        policy = self._policy()
        self.assertTrue(policy.sign_in_if_needed)
        self.assertTrue(policy.create_account_if_missing)
        self.assertTrue(policy.reuse_email_across_portals)
        self.assertTrue(policy.allow_configured_password_reuse)
        self.assertEqual(policy.credentials_source, "local_secret_only")
        self.assertEqual(policy.duplicate_cooldown_days, 90)


if __name__ == "__main__":
    unittest.main()
