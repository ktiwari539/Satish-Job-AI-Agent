import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from certify_linkedin import summarize


class CertificationReport(unittest.TestCase):
    def test_review_without_release_evidence_never_passes_acceptance(self):
        rows = [dict(job_id=str(i), flow_tested=True, review_reached=True) for i in range(10)]
        self.assertFalse(summarize(rows)['acceptance_passed'])

    def test_duplicates_cannot_satisfy_ten_distinct_jobs(self):
        rows = [dict(job_id='9000000001', flow_tested=True, release_checks_passed=True)] * 10
        self.assertEqual(summarize(rows)['distinct_application_forms_exercised'], 1)
        self.assertFalse(summarize(rows)['acceptance_passed'])

    def test_entry_only_results_are_not_application_form_tests(self):
        rows = [dict(job_id=str(i), flow_tested=False) for i in range(10)]
        self.assertEqual(summarize(rows)['distinct_application_forms_exercised'], 0)
        self.assertFalse(summarize(rows)['acceptance_passed'])

    def test_ten_distinct_forms_and_one_verified_review_pass_measured_gate(self):
        rows = [dict(job_id=str(i), flow_tested=True, release_checks_passed=i == 0) for i in range(10)]
        self.assertTrue(summarize(rows)['acceptance_passed'])
        self.assertEqual(summarize(rows)['submitted'], 0)
