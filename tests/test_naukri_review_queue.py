import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from naukri_review_queue import qualified_jobs, open_in_regular_chrome, main


def report():
    return {
        "portal": "naukri", "mode": "READ_ONLY",
        "submitted": 0, "confirmed": 0, "threshold": 75,
        "jobs": [
            {"title": "Customer Success Manager", "company": "Company A", "score": 83,
             "status": "QUALIFIED_FOR_REVIEW", "url": "https://www.naukri.com/job-listings-a-123"},
            {"title": "Support Manager", "company": "Company B", "score": 91,
             "status": "QUALIFIED_FOR_REVIEW", "url": "https://www.naukri.com/job-listings-b-789"},
            {"title": "Other", "company": "Company C", "score": 42,
             "status": "BELOW_MATCH_THRESHOLD", "url": "https://www.naukri.com/job-listings-c-456"},
        ]
    }


class NaukriReviewQueueTests(unittest.TestCase):
    def test_prioritizes_highest_score(self):
        results = qualified_jobs(report())
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["score"], 91)

    def test_requires_existing_qualified_decision_and_threshold(self):
        data = report()
        data["jobs"][0]["score"] = 74
        with self.assertRaisesRegex(ValueError, "invalid_qualified_job"):
            qualified_jobs(data)

    def test_rejects_untrusted_domain_and_duplicate(self):
        data = report()
        data["jobs"][0]["url"] = "https://evil.example/"
        with self.assertRaisesRegex(ValueError, "invalid_qualified_job"):
            qualified_jobs(data)
        data = report()
        data["jobs"].append(dict(data["jobs"][0]))
        self.assertEqual(len(qualified_jobs(data)), 2)

    def test_rejects_non_read_only_report(self):
        for key, value in [("mode", "LIVE"), ("submitted", 1), ("confirmed", 1)]:
            data = report()
            data[key] = value
            with self.assertRaises(ValueError):
                qualified_jobs(data)

    def test_chrome_open_only_targets_supported_naukri_host(self):
        with patch("naukri_review_queue.platform.system", return_value="Darwin"):
            with patch("naukri_review_queue.subprocess.run") as run:
                open_in_regular_chrome("https://www.naukri.com/job-listings-a-123")
                run.assert_called_once()
                args = run.call_args.args[0]
                self.assertEqual(args[:3], ["open", "-a", "Google Chrome"])
            with patch("naukri_review_queue.subprocess.run") as run:
                with self.assertRaises(ValueError):
                    open_in_regular_chrome("https://evil.example/")
                run.assert_not_called()

    def test_cli_opens_only_one_qualified_job_on_explicit_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.json"
            report_path.write_text(json.dumps(report()), encoding="utf-8")
            with patch.object(sys, "argv", ["naukri_review_queue.py", "--report", str(report_path), "--open-first"]):
                with patch("naukri_review_queue.open_in_regular_chrome") as chrome:
                    from contextlib import redirect_stdout
                    from io import StringIO
                    output = StringIO()
                    with redirect_stdout(output):
                        status = main()
            self.assertEqual(status, 0)
            chrome.assert_called_once_with("https://www.naukri.com/job-listings-b-789")
            self.assertTrue(json.loads(output.getvalue())["opened"])


if __name__ == "__main__":
    unittest.main()
