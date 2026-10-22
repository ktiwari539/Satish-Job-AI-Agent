"""Local Mumbai profile updates never touch browser, credentials or other fields."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import job_agent_cli
from local_profile_city import read_applicant_city, set_applicant_city


class LocalProfileCityTests(unittest.TestCase):
    def test_updates_only_city_and_preserves_unrelated_data(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "private_profile.json"
            before = {"location": "Pune", "email": "secret@example.com",
                      "answers": {"visa_status": "No"}}
            p.write_text(json.dumps(before))
            city = set_applicant_city(str(p), "Mumbai")
            self.assertEqual(city, "Mumbai")
            after = json.loads(p.read_text())
            self.assertEqual(after["location"], "Mumbai")
            self.assertEqual(after["email"], before["email"])
            self.assertEqual(after["answers"], before["answers"])
            self.assertEqual(read_applicant_city(str(p)), "Mumbai")
            self.assertFalse(any(x.name.startswith(".profile-city-") for x in p.parent.iterdir()))
            if os.name == "posix":
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_missing_profile_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "private_profile.json"
            with self.assertRaises(FileNotFoundError):
                set_applicant_city(str(p), "Mumbai")
            self.assertFalse(p.exists())

    def test_blank_or_control_city_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "private_profile.json"
            p.write_text('{"location":"Pune"}')
            for city in ("", "../Mumbai", "Mumbai\nfoo", "Mumbai; rm -rf ~"):
                with self.subTest(city=city), self.assertRaises(ValueError):
                    set_applicant_city(str(p), city)
            self.assertEqual(read_applicant_city(str(p)), "Pune")

    def test_cli_local_update_never_calls_live_application(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "private_profile.json"
            p.write_text('{"location":"India", "name":"private"}')
            args = SimpleNamespace(
                set_profile_city="Mumbai", private_profile=str(p),
                check_applied_status_only=False,
            )
            with patch("job_agent_cli.PlaywrightSession") as browser, \
                 patch("job_agent_cli.run_linkedin_application") as apply, \
                 redirect_stdout(io.StringIO()) as out:
                code = job_agent_cli._run(args)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["status"], "profile_city_updated")
            self.assertEqual(read_applicant_city(str(p)), "Mumbai")
            browser.assert_not_called()
            apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
