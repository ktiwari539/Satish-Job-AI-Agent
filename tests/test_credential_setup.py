import json
import os
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from credential_setup import save_credentials
from local_credentials import load_portal_credentials


class CredentialSetupTests(unittest.TestCase):
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
