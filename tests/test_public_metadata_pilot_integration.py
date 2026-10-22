"""CLI scoring from a public exact-ID LinkedIn JD, never a similar role."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import job_agent_cli
from models import Job

DIRECT = "https://www.linkedin.com/jobs/view/4461542106/"
PUBLIC = "https://in.linkedin.com/jobs/view/sr-customer-success-manager-at-firework-4461542106"
PUBLIC_BAD = "https://in.linkedin.com/jobs/view/other-job-4476701830"


def args(url=PUBLIC):
    return SimpleNamespace(
        portal="linkedin", job_url=DIRECT, public_job_url=url,
        profile="config/qa_profile.json", db="data/jobs.db",
        profile_dir="browser-profile", headless=False, query="Customer Success Manager",
    )


def qualified_job():
    return Job(
        source="linkedin", external_id="4461542106",
        company="Firework", title="Sr. Customer Success Manager",
        location="India", url=DIRECT,
        description="Customer success enterprise account management. " * 20,
        required_skills=("customer success", "stakeholder management", "retention"),
        minimum_years=7,
        remote=True,
    )


class PublicLinkedInCliTests(unittest.TestCase):
    def test_read_only_qualification_uses_same_id_public_jd_after_dom_failure(self):
        runtime = MagicMock()
        session = SimpleNamespace(authenticated=True, needs_human_action=False)
        store = MagicMock()
        store.is_recent_similar_application.return_value = False
        with patch("job_agent_cli._load_json", return_value={}), \
             patch("job_agent_cli.CandidateProfile.from_dict") as profile, \
             patch("job_agent_cli.JobStore", return_value=store), \
             patch("job_agent_cli.PlaywrightSession", return_value=runtime), \
             patch("job_agent_cli.LinkedInBrowserAdapter") as adapter, \
             patch("job_agent_cli.inspect_exact_linkedin_job",
                   side_effect=ValueError(
                       "exact_job_metadata_unverified:title,company,location:no_job_details_in_dom"
                   )) as direct, \
             patch("job_agent_cli.fetch_public_exact_linkedin_job",
                   return_value=qualified_job()) as fetch, \
             patch("job_agent_cli.score_profile",
                   return_value=SimpleNamespace(decision="APPLY", score=86)), \
             patch("job_agent_cli.evaluate_eligibility",
                   return_value=SimpleNamespace(eligible=True, reasons=())), \
             patch("job_agent_cli.inspect_selected_search_job") as search, \
             patch("job_agent_cli.trace_event"), \
             redirect_stdout(io.StringIO()) as output:
            profile.return_value.skill_taxonomy = ("customer success", "retention")
            adapter.return_value.login_state.return_value = session
            code = job_agent_cli._inspect_one_linkedin_job(args())
        self.assertEqual(code, 0)
        self.assertEqual(direct.call_count, 1)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[1].job_id, "4461542106")
        search.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "exact_job_qualified_for_pilot")
        self.assertTrue(result["live_pilot_ready"])
        self.assertEqual(result["inspection_route"], "same_id_verified_public_linkedin")
        self.assertEqual(result["job_id"], "4461542106")
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(result["confirmed"], 0)

    def test_public_url_for_another_id_is_rejected_before_browser(self):
        with patch("job_agent_cli.PlaywrightSession") as runtime, \
             redirect_stdout(io.StringIO()) as output:
            code = job_agent_cli._inspect_one_linkedin_job(args(PUBLIC_BAD))
        self.assertEqual(code, 2)
        runtime.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "public_job_url_rejected")

    def test_failed_public_fetch_does_not_fall_through_to_random_job(self):
        runtime = MagicMock()
        session = SimpleNamespace(authenticated=True, needs_human_action=False)
        with patch("job_agent_cli._load_json", return_value={}), \
             patch("job_agent_cli.CandidateProfile.from_dict") as profile, \
             patch("job_agent_cli.JobStore"), \
             patch("job_agent_cli.PlaywrightSession", return_value=runtime), \
             patch("job_agent_cli.LinkedInBrowserAdapter") as adapter, \
             patch("job_agent_cli.inspect_exact_linkedin_job",
                   side_effect=ValueError(
                       "exact_job_metadata_unverified:title,company,location:no_job_details_in_dom"
                   )), \
             patch("job_agent_cli.fetch_public_exact_linkedin_job",
                   side_effect=ValueError("public_exact_job_metadata_incomplete")), \
             patch("job_agent_cli.inspect_selected_search_job") as search, \
             patch("job_agent_cli.trace_event"), \
             redirect_stdout(io.StringIO()) as output:
            profile.return_value.skill_taxonomy = ()
            adapter.return_value.login_state.return_value = session
            code = job_agent_cli._inspect_one_linkedin_job(args())
        self.assertEqual(code, 4)
        search.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "exact_job_inspection_blocked")
        self.assertIn("public_fallback", result["reason"])
        self.assertEqual(result["attempted"], 0)
        self.assertEqual(result["confirmed"], 0)


if __name__ == "__main__":
    unittest.main()
