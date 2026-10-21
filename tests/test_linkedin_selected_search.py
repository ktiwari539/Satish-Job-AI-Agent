"""No cross-job selection in LinkedIn read-only search fallback."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from linkedin_exact_job import parse_linkedin_target
from linkedin_selected_search import inspect_selected_search_job
from models import Job
import job_agent_cli

TARGET = parse_linkedin_target("https://www.linkedin.com/jobs/view/4476701830/")
DETAILS = "Customer success, stakeholder management, onboarding and SLA. " * 10
URL = (
    "https://www.linkedin.com/jobs/search-results/"
    "?currentJobId=4476701830&keywords=Customer+Success+Manager"
)


class Value:
    def __init__(self, val, visible=True):
        self.val = val
        self.visible = visible
    def is_visible(self):
        return self.visible
    def inner_text(self, timeout=0):
        return self.val
    def count(self):
        return bool(self.val)
    @property
    def first(self):
        return self


class Collection:
    def __init__(self, values):
        self.values = values
    def count(self):
        return len(self.values)
    def nth(self, i):
        return self.values[i]


class Card:
    def __init__(self, job_id, *, visible=True):
        self.job_id = job_id
        self.visible = visible
        self.clicked = 0
    def get_attribute(self, key):
        return self.job_id if key == "data-job-id" else None
    def is_visible(self):
        return self.visible
    def click(self, timeout=0):
        self.clicked += 1


class Detail:
    def __init__(self):
        self.text = {
            ".job-details-jobs-unified-top-card__job-title": "Customer Success Manager",
            ".job-details-jobs-unified-top-card__company-name": "Example Firm",
            ".job-details-jobs-unified-top-card__primary-description-container": "India",
            ".jobs-description__content": DETAILS,
        }
    def is_visible(self):
        return True
    def locator(self, selector):
        value = self.text.get(selector, "")
        return Collection([Value(value)]) if value else Collection([])


class Page:
    def __init__(self, cards, detail=True):
        self.url = URL
        self.cards = cards
        self.detail = detail
        self.waits = 0
    def locator(self, selector):
        if selector.startswith("li.scaffold-layout__list-item"):
            return Collection(self.cards)
        if selector == ".jobs-search__job-details--container" and self.detail:
            return Collection([Detail()])
        return Collection([])
    def wait_for_timeout(self, ms):
        self.waits += 1


class SelectedSearchTests(unittest.TestCase):
    def test_read_only_selects_only_the_exact_job_id(self):
        wrong = Card("4477371718")
        right = Card("4476701830")
        page = Page([wrong, right])
        with patch("linkedin_selected_search.bounded_goto"):
            job = inspect_selected_search_job(
                page, TARGET, ("customer success", "stakeholder management", "onboarding", "sla")
            )
        self.assertEqual(job.external_id, "4476701830")
        self.assertEqual(job.title, "Customer Success Manager")
        self.assertEqual(job.company, "Example Firm")
        self.assertEqual(len(job.required_skills), 4)
        self.assertEqual(right.clicked, 1)
        self.assertEqual(wrong.clicked, 0)

    def test_no_exact_target_card_never_clicks_other_job(self):
        wrong = Card("4477371718")
        with patch("linkedin_selected_search.bounded_goto"):
            with self.assertRaisesRegex(ValueError, "not_unique_or_not_found"):
                inspect_selected_search_job(Page([wrong]), TARGET, ())
        self.assertEqual(wrong.clicked, 0)

    def test_ambiguous_duplicate_cards_fail_without_click(self):
        cards = [Card("4476701830"), Card("4476701830")]
        with patch("linkedin_selected_search.bounded_goto"):
            with self.assertRaisesRegex(ValueError, "not_unique_or_not_found"):
                inspect_selected_search_job(Page(cards), TARGET, ())
        self.assertEqual(sum(card.clicked for card in cards), 0)

    def test_selected_card_without_verified_details_still_fails(self):
        right = Card("4476701830")
        with patch("linkedin_selected_search.bounded_goto"):
            with self.assertRaisesRegex(ValueError, "selected_detail_unverified"):
                inspect_selected_search_job(Page([right], detail=False), TARGET, ())
        self.assertEqual(right.clicked, 1)

    def test_wrong_url_id_fails_before_click(self):
        card = Card("4476701830")
        page = Page([card])
        page.url = "https://www.linkedin.com/jobs/search/?currentJobId=4477371718"
        with patch("linkedin_selected_search.bounded_goto"):
            with self.assertRaisesRegex(ValueError, "route_id_unverified"):
                inspect_selected_search_job(page, TARGET, ())
        self.assertEqual(card.clicked, 0)


class CLIReadOnlyFallbackTests(unittest.TestCase):
    def test_blank_direct_job_can_be_checked_in_search_without_submit(self):
        args = SimpleNamespace(
            portal="linkedin", job_url=TARGET.url,
            query="Customer Success Manager", profile="profile.json",
            db="test.db", profile_dir="browser-profile", headless=False,
            inspect_job_only=True,
        )
        profile = {
            "target_roles": ["customer success manager"],
            "skills": ["customer success", "sla", "stakeholder management", "onboarding"],
            "skill_taxonomy": ["customer success", "sla", "stakeholder management", "onboarding"],
            "preferred_locations": ["india"], "remote_allowed": True,
            "total_experience_years": 8, "india_authorized": True,
            "outside_india_sponsorship_required": True,
        }
        job = Job("linkedin", "4476701830", "Example Firm",
                  "Customer Success Manager", "India", TARGET.url, DETAILS,
                  required_skills=("customer success", "sla", "stakeholder management", "onboarding"))
        runtime = MagicMock()
        adapter = MagicMock()
        adapter.login_state.return_value = SimpleNamespace(authenticated=True, needs_human_action=False, reason="")
        store = MagicMock()
        store.is_recent_similar_application.return_value = False
        with patch("job_agent_cli._load_json", return_value=profile), \
             patch("job_agent_cli.JobStore", return_value=store), \
             patch("job_agent_cli.PlaywrightSession", return_value=runtime), \
             patch("job_agent_cli.LinkedInBrowserAdapter", return_value=adapter), \
             patch("job_agent_cli.inspect_exact_linkedin_job",
                   side_effect=ValueError("exact_job_metadata_unverified:title,company,location:no_job_details_in_dom")), \
             patch("job_agent_cli.inspect_selected_search_job", return_value=job) as retry, \
             patch("job_agent_cli.run_linkedin_application") as submit, \
             redirect_stdout(io.StringIO()) as out:
            code = job_agent_cli._run(args)
        self.assertEqual(code, 0)
        retry.assert_called_once()
        submit.assert_not_called()
        result = json.loads(out.getvalue())
        self.assertEqual(result["status"], "exact_job_qualified_read_only")
        self.assertFalse(result["live_pilot_ready"])
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(result["confirmed"], 0)

    def test_direct_job_security_checkpoint_cannot_use_search_fallback(self):
        args = SimpleNamespace(portal="linkedin", job_url=TARGET.url,
                               profile="profile.json", db="db", profile_dir="profile",
                               headless=False, inspect_job_only=True)
        runtime = MagicMock()
        adapter = MagicMock()
        adapter.login_state.return_value = SimpleNamespace(authenticated=True, needs_human_action=False, reason="")
        with patch("job_agent_cli._load_json", return_value={}), \
             patch("job_agent_cli.JobStore"), \
             patch("job_agent_cli.PlaywrightSession", return_value=runtime), \
             patch("job_agent_cli.LinkedInBrowserAdapter", return_value=adapter), \
             patch("job_agent_cli.inspect_exact_linkedin_job",
                   side_effect=ValueError("exact_job_metadata_unverified:title,company,location:security_checkpoint")), \
             patch("job_agent_cli.inspect_selected_search_job") as fallback, \
             redirect_stdout(io.StringIO()):
            code = job_agent_cli._run(SimpleNamespace(**vars(args)))
        self.assertEqual(code, 4)
        fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
