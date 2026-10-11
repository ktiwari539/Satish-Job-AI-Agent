import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from local_credentials import load_portal_credentials


class LocalCredentialsTests(unittest.TestCase):
    def test_loads_one_portal_without_logging_or_transforming_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "credentials.json"
            path.write_text(
                json.dumps({
                    "linkedin": {
                        "email": "candidate@example.invalid",
                        "password": "local-only-password",
                    }
                }),
                encoding="utf-8",
            )
            credentials = load_portal_credentials(str(path), "linkedin")
            self.assertEqual(credentials.email, "candidate@example.invalid")
            self.assertEqual(credentials.password, "local-only-password")
            self.assertTrue(credentials.complete())

    def test_missing_portal_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "credentials.json"
            path.write_text(json.dumps({"linkedin": {}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_portal_credentials(str(path), "naukri")


if __name__ == "__main__":
    unittest.main()
