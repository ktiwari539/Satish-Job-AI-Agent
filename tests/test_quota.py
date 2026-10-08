import tempfile
import unittest
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from automation_policy import AutomationPolicy, ApplicationWindow
from models import Job
from quota import evaluate_application_quota
from store import JobStore


class QuotaTests(unittest.TestCase):
    def _policy(self):
        from datetime import time
        return AutomationPolicy(
            timezone="Asia/Kolkata",
            threshold=75,
            daily_success_cap=100,
            count_only_confirmed_submissions=True,
            stop_at_window_end=True,
            windows=(
                ApplicationWindow("morning", time(10, 0), time(12, 0), 50),
                ApplicationWindow("night", time(23, 0), time(1, 0), 50),
            ),
            sign_in_if_needed=True,
            create_account_if_missing=True,
            reuse_email_across_portals=True,
            allow_configured_password_reuse=True,
            credentials_source="local_secret_only",
            duplicate_cooldown_days=90,
        )

    def test_outside_window_blocks_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            status = evaluate_application_quota(
                self._policy(),
                store,
                now=datetime(2026, 10, 7, 15, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
            )
            self.assertFalse(status.allowed)
            self.assertEqual(status.reason, "outside_application_window")

    def test_failed_or_unconfirmed_rows_do_not_consume_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            job = Job("linkedin", "1", "A", "Role", "India", "https://example.invalid/1", "")
            store.mark_applied(job)
            status = evaluate_application_quota(
                self._policy(),
                store,
                now=datetime(2026, 10, 7, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
            )
            self.assertTrue(status.allowed)
            self.assertEqual(status.window_confirmed, 0)
            self.assertEqual(status.daily_confirmed, 0)

    def test_night_window_after_midnight_uses_same_operational_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            status = evaluate_application_quota(
                self._policy(),
                store,
                now=datetime(2026, 10, 8, 0, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
            )
            self.assertTrue(status.allowed)
            self.assertEqual(status.active_window, "night")
            self.assertTrue(status.window_start.startswith("2026-10-07T23:00:00"))
            self.assertTrue(status.operational_day_start.startswith("2026-10-07T10:00:00"))


if __name__ == "__main__":
    unittest.main()
