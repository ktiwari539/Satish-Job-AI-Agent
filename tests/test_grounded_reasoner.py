"""No AI-invented answer: local model chooses fact KEY; Python owns values."""
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from grounded_reasoner import (
    LocalGroundedReasoner, configure_local_reasoner, resolve_with_local_reasoner,
)
from question_resolver import resolve_application_answer


class _FakeResponse:
    status = 200

    def __init__(self, key):
        self.key = key

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *args, **kwargs):
        return json.dumps({
            "response": json.dumps({"fact_key": self.key})
        }).encode("utf-8")


class GroundedReasonerTests(unittest.TestCase):
    def tearDown(self):
        configure_local_reasoner("")

    def _resolve(self, key, question, profile, options=()):
        model = LocalGroundedReasoner("qwen2.5:7b")
        with patch("grounded_reasoner.request.urlopen", return_value=_FakeResponse(key)) as call:
            result = model.resolve(question, profile, options)
            self.assertEqual(call.call_count, 1)
            req = call.call_args.args[0]
            self.assertEqual(req.full_url, "http://127.0.0.1:11434/api/generate")
            payload = json.loads(req.data)
            # No private fact VALUES are shared, only the names of available facts.
            for value in profile.values():
                if isinstance(value, str) and len(value) >= 3:
                    self.assertNotIn(value, payload["prompt"])
            return result

    def test_unfamiliar_joining_question_maps_to_exact_saved_fact(self):
        result = self._resolve(
            "notice_period_days", "After how many days could you join our team?",
            {"notice_period_days": 30}, ("Immediate", "15 days", "30 days", "60 days"),
        )
        self.assertEqual(result.state, "resolved")
        self.assertEqual(result.fact_key, "notice_period_days")
        self.assertEqual(result.answer, "30 days")

    def test_does_not_allow_llm_to_invent_profile_values(self):
        result = self._resolve("fictional_key", "After how many days could you join?",
                               {"notice_period_days": 30})
        self.assertEqual(result.state, "model_not_grounded")

    def test_avoid_mapping_general_years_to_specific_skill(self):
        model = LocalGroundedReasoner("qwen2.5:7b")
        self.assertFalse(model._scope_ok(
            "How many years of experience do you have with Salesforce?",
            "total_experience_years",
        ))
        self.assertFalse(model._scope_ok(
            "How many years of technical experience do you have?",
            "total_experience_years",
        ))

    def test_generic_experience_does_not_prove_specific_tool_tenure(self):
        """Experience with a technology needs its own verified fact."""
        model = LocalGroundedReasoner("qwen2.5:7b")
        for question in (
            "How many total years of experience do you have with Kubernetes?",
            "How many overall years of experience using Splunk?",
            "How many years of professional experience in Terraform?",
        ):
            with self.subTest(question=question):
                self.assertFalse(model._scope_ok(
                    question, "total_experience_years"
                ))

    def test_boolean_threshold_cannot_use_model_guess(self):
        model = LocalGroundedReasoner("qwen2.5:7b")
        with patch("grounded_reasoner.request.urlopen") as http:
            result = model.resolve(
                "Do you have experience managing an insurance BPO?",
                {"total_experience_years": 8}, ("Yes", "No"),
            )
        self.assertNotEqual(result.state, "resolved")
        http.assert_not_called()

    def test_subjective_question_does_not_leak_or_invent(self):
        model = LocalGroundedReasoner("qwen2.5:7b")
        for question in (
            "Why do you want to join our company?",
            "Describe your biggest achievement in customer success",
            "Would you move to Bangalore tomorrow?",
            "Is your current notice period negotiable?",
        ):
            with self.subTest(question=question), \
                 patch("grounded_reasoner.request.urlopen") as http:
                outcome = model.resolve(
                    question, {"notice_period_days": 30,
                               "customer_success_years": 5,
                               "current_company": "Private Employer"},
                )
                self.assertNotEqual(outcome.state, "resolved")
                http.assert_not_called()

    def test_missing_verified_fact_never_calls_ai(self):
        model = LocalGroundedReasoner("qwen2.5:7b")
        with patch("grounded_reasoner.request.urlopen") as http:
            result = model.resolve("After how many days could you join?", {}, ())
        self.assertEqual(result.state, "no_verified_fact")
        http.assert_not_called()

    def test_disallowed_remote_model_url(self):
        for name in ("https://evil.example/api", "http://127.0.0.1:11434", "",
                     "../../forbidden", "bad model\n"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    LocalGroundedReasoner(name)

    def test_missing_local_server_fails_closed(self):
        from urllib.error import URLError
        model = LocalGroundedReasoner("qwen2.5:7b")
        with patch("grounded_reasoner.request.urlopen", side_effect=URLError("offline")):
            result = model.resolve("After how many days could you join?",
                                   {"notice_period_days": 30})
        self.assertEqual(result.state, "model_unavailable")
        self.assertEqual(result.answer, "")

    def test_semantic_path_is_disabled_by_default(self):
        configure_local_reasoner("")
        result = resolve_application_answer(
            "Kindly provide your joining lead time",
            {"notice_period_days": 30},
            options=("30 days", "60 days"),
        )
        self.assertEqual(result.status, "UNKNOWN_REQUIRED")

    def test_opted_in_semantic_path_only_uses_verified_profile_value(self):
        configure_local_reasoner("qwen2.5:7b")
        with patch("grounded_reasoner.request.urlopen",
                   return_value=_FakeResponse("notice_period_days")):
            result = resolve_application_answer(
                "Kindly provide your joining lead time",
                {"notice_period_days": 30},
                options=("30 days", "60 days"),
            )
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual(result.answer, "30 days")
        self.assertEqual(result.source, "local_verified_fact:notice_period_days")

    def test_invalid_option_blocks_instead_of_submitting(self):
        result = self._resolve("notice_period_days",
                               "Kindly provide your joining lead time",
                               {"notice_period_days": 30},
                               ("Immediate", "60 days"))
        self.assertEqual(result.state, "option_mismatch")


if __name__ == "__main__":
    unittest.main()
