import json
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from extractor import extract_skills
from sources import parse_greenhouse, parse_lever


class SourceParserTests(unittest.TestCase):
    def test_greenhouse_parser(self):
        payload = json.loads((ROOT / "tests/fixtures/greenhouse.json").read_text())
        jobs = parse_greenhouse(payload, "example", ("customer success", "sla", "incident management"))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source, "greenhouse")
        self.assertIn("sla", jobs[0].required_skills)
        self.assertEqual(jobs[0].minimum_years, 5)
        self.assertTrue(jobs[0].remote)

    def test_lever_parser(self):
        payload = json.loads((ROOT / "tests/fixtures/lever.json").read_text())
        jobs = parse_lever(payload, "example", ("technical support", "jira", "automation"))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source, "lever")
        self.assertIn("jira", jobs[0].required_skills)
        self.assertEqual(jobs[0].minimum_years, 6)

    def test_skill_extraction_handles_punctuation(self):
        found = extract_skills(
            "Own SLA. Jira, REST API; and customer success.",
            ("sla", "jira", "rest api", "customer success"),
        )
        self.assertEqual(
            found,
            ("customer success", "jira", "rest api", "sla"),
        )


if __name__ == "__main__":
    unittest.main()
