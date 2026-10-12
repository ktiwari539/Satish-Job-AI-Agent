import json
import os
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from credential_setup import remove_credentials, save_credentials
from local_credentials import load_portal_credentials


class CredentialSetupTests(unittest.TestCase):
    def test_removes_only_obsolete_naukri_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portal_credentials.json"
            save_credentials(str(path), "linkedin", "candidate@example.invalid", "linked")
            save_credentials(str(path), "naukri", "candidate@example.invalid", "obsolete")
            self.assertTrue(remove_credentials(str(path), "naukri"))
            contents = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("naukri", contents)
            self.assertEqual(contents["linkedin"]["password"], "linked")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertFalse(remove_credentials(str(path), "naukri"))

    def test_refuses_to_destroy_invalid_credential_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portal_credentials.json"
            path.write_text("{invalid", encoding="utf-8")
            with self.assertRaises(ValueError):
                remove_credentials(str(path), "naukri")
            self.assertEqual(path.read_text(encoding="utf-8"), "{invalid")

    def test_saves_local_credentials_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portal_credentials.json"
            saved = save_credentials(
                str(path),
                "external_default",
                "candidate@example.invalid",
                "local-secret",
            )
            self.assertEqual(saved, path.resolve())
            mode = os.stat(path).st_mode & 0o777
            self.assertEqual(mode, 0o600)
            loaded = load_portal_credentials(str(path), "external_default")
            self.assertEqual(loaded.email, "candidate@example.invalid")
            self.assertEqual(loaded.password, "local-secret")


if __name__ == "__main__":
    unittest.main()
