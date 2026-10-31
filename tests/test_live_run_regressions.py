import tempfile
import unittest
import zipfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from application_forms import FormField, build_fill_plan
from matcher import score_profile
from models import CandidateProfile, Job
from resume_facts import derive_resume_facts


class LiveRunRegressionTests(unittest.TestCase):
    def test_superset_screening_questions_use_verified_profile_values(self):
        profile = {
            "customer_success_years": "7",
            "current_ctc": "12.5 LPA",
            "expected_ctc": "19 LPA",
            "notice_period": "30 days",
        }
        fields = (
            FormField("q1", "How many years of experience do you have with Customer Success?", True),
            FormField("q2", "What is your current CTC?", True),
            FormField("q3", "What is your expected CTC?", True),
            FormField("q4", "What is your notice period?", True),
        )

        plan = build_fill_plan(fields, profile, live_submission_enabled=True)

        self.assertEqual(plan.unknown_required_fields, ())
        self.assertEqual(plan.missing_profile_values, ())
        self.assertEqual(plan.values["q1"], "7")
        self.assertEqual(plan.values["q2"], "1250000")
        self.assertEqual(plan.values["q3"], "1900000")
        self.assertEqual(plan.values["q4"], "30 days")

    def test_resume_derives_explicit_customer_success_years(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resume.docx"
            document_xml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:r><w:t>'
                'Customer success experience: 7 years.'
                '</w:t></w:r></w:p></w:body></w:document>'
            )
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", document_xml)

            facts = derive_resume_facts(str(path))

        self.assertEqual(facts["customer_success_years"], "7")

    def test_cx_title_is_treated_as_customer_experience(self):
        profile = CandidateProfile.from_dict({
            "target_roles": ["customer experience manager"],
            "skills": ["customer support", "retention", "team leadership", "csat"],
            "preferred_locations": ["india"],
            "remote_allowed": True,
            "total_experience_years": 8,
            "india_authorized": True,
            "outside_india_sponsorship_required": True,
        })
        job = Job(
            "linkedin",
            "life-guru",
            "LifeGuru",
            "Assistant Manager – CX & Customer Retention",
            "India",
            "https://example.invalid/job",
            "Customer support retention team leadership CSAT",
            required_skills=("customer support", "retention", "team leadership", "csat"),
        )

        result = score_profile(profile, job, threshold=75)

        self.assertGreaterEqual(result.role_score, 55)
        self.assertEqual(result.decision, "APPLY")


if __name__ == "__main__":
    unittest.main()
