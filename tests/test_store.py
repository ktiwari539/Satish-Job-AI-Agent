import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models import Job
from store import JobStore


class StoreTests(unittest.TestCase):
    def test_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            job = Job("demo", "1", "A", "Role", "India", "https://example.invalid", "")
            self.assertFalse(store.is_duplicate(job))
            store.mark_seen(job)
            self.assertTrue(store.is_duplicate(job))

    def test_recent_similar_application_is_blocked_for_90_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            first = Job(
                "linkedin", "1", "Example",
                "Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/1", "same role",
            )
            repost = Job(
                "linkedin", "2", "Example",
                "Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/2", "same role repost",
            )
            store.mark_submission_confirmed(first)
            self.assertTrue(store.is_recent_similar_application(repost, cooldown_days=90))

    def test_material_location_change_can_be_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            first = Job(
                "linkedin", "1", "Example",
                "Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/1", "",
            )
            moved = Job(
                "linkedin", "2", "Example",
                "Customer Success Manager",
                "Bengaluru, India", "https://linkedin.invalid/2", "",
            )
            store.mark_submission_confirmed(first)
            self.assertFalse(
                store.is_recent_similar_application(
                    moved,
                    cooldown_days=90,
                    allow_material_location_change=True,
                )
            )


    def test_seniority_variant_is_treated_as_same_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            first = Job(
                "linkedin", "1", "Example",
                "Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/1", "",
            )
            senior_repost = Job(
                "linkedin", "2", "Example",
                "Senior Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/2", "",
            )
            store.mark_submission_confirmed(first)
            self.assertTrue(store.is_recent_similar_application(senior_repost))

    def test_company_suffix_variant_is_treated_as_same_company(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            first = Job(
                "linkedin", "1", "Example Pvt Ltd",
                "Support Manager",
                "Mumbai, India", "https://linkedin.invalid/1", "",
            )
            repost = Job(
                "indeed", "2", "Example",
                "Customer Support Manager",
                "Mumbai, India", "https://indeed.invalid/2", "",
            )
            store.mark_submission_confirmed(first)
            self.assertTrue(store.is_recent_similar_application(repost))

    def test_different_role_at_same_company_is_not_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            first = Job(
                "linkedin", "1", "Example",
                "Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/1", "",
            )
            different = Job(
                "linkedin", "2", "Example",
                "Technical Operations Manager",
                "Mumbai, India", "https://linkedin.invalid/2", "",
            )
            store.mark_submission_confirmed(first)
            self.assertFalse(store.is_recent_similar_application(different))

    def test_location_formatting_change_does_not_bypass_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            first = Job(
                "linkedin", "1", "Example",
                "Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/1", "",
            )
            formatted = Job(
                "linkedin", "2", "Example",
                "Customer Success Manager",
                "Mumbai, Maharashtra, India", "https://linkedin.invalid/2", "",
            )
            store.mark_submission_confirmed(first)
            self.assertTrue(store.is_recent_similar_application(formatted))

    def test_material_full_jd_change_can_bypass_cooldown(self):
        old_description = " ".join(
            [
                "customer onboarding adoption renewals retention success planning "
                "stakeholder engagement health scoring qbr expansion advocacy"
            ] * 5
        )
        new_description = " ".join(
            [
                "incident response technical support escalation debugging operations "
                "monitoring reliability sla troubleshooting root cause automation"
            ] * 5
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            first = Job(
                "linkedin", "1", "Example",
                "Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/1", old_description,
            )
            changed = Job(
                "linkedin", "2", "Example",
                "Senior Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/2", new_description,
            )
            store.mark_submission_confirmed(first)
            self.assertFalse(
                store.is_recent_similar_application(
                    changed,
                    allow_material_description_change=True,
                )
            )

    def test_minor_jd_edit_does_not_bypass_cooldown(self):
        base = " ".join(
            [
                "customer onboarding adoption renewals retention success planning "
                "stakeholder engagement health scoring qbr expansion advocacy"
            ] * 5
        )
        minor_edit = base + " collaborate closely with sales leadership"
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            first = Job(
                "linkedin", "1", "Example",
                "Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/1", base,
            )
            repost = Job(
                "linkedin", "2", "Example",
                "Senior Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/2", minor_edit,
            )
            store.mark_submission_confirmed(first)
            self.assertTrue(store.is_recent_similar_application(repost))

    def test_short_or_missing_jd_fails_closed_for_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            first = Job(
                "linkedin", "1", "Example",
                "Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/1", "short description",
            )
            repost = Job(
                "linkedin", "2", "Example",
                "Senior Customer Success Manager",
                "Mumbai, India", "https://linkedin.invalid/2", "different short text",
            )
            store.mark_submission_confirmed(first)
            self.assertTrue(store.is_recent_similar_application(repost))

    def test_only_confirmed_submissions_count_toward_window_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            confirmed = Job(
                "linkedin", "1", "A", "Role A", "India",
                "https://linkedin.invalid/1", "",
            )
            manual = Job(
                "linkedin", "2", "B", "Role B", "India",
                "https://linkedin.invalid/2", "",
            )
            store.mark_submission_confirmed(confirmed)
            store.mark_applied(manual)
            now = datetime.now(timezone.utc)
            count = store.count_confirmed_submissions(
                start_utc=now - timedelta(minutes=5),
                end_utc=now + timedelta(minutes=5),
            )
            self.assertEqual(count, 1)

    def test_cross_portal_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(str(Path(tmp) / "jobs.db"))
            first = Job(
                "linkedin", "1", "Example Pvt Ltd",
                "Customer Success Manager - Remote",
                "Mumbai, India", "https://linkedin.invalid/1", "",
            )
            second = Job(
                "indeed", "99", "Example",
                "Customer Success Manager",
                "Mumbai, India", "https://indeed.invalid/99", "",
            )
            store.mark_seen(first)
            self.assertTrue(store.is_duplicate(second))


if __name__ == "__main__":
    unittest.main()
