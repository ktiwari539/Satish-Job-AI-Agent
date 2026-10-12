import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from resume_store import current_resume_metadata, import_resume, resolve_current_resume


class ResumeStoreTests(unittest.TestCase):
    def test_import_copies_resume_into_agent_owned_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Satish Resume.pdf"
            source.write_bytes(b"%PDF-test-resume")
            vault = root / "vault"

            imported = import_resume(str(source), str(vault))

            self.assertTrue(imported.exists())
            self.assertNotEqual(imported, source.resolve())
            self.assertEqual(imported.parent, vault.resolve())
            self.assertEqual(imported.read_bytes(), source.read_bytes())

            metadata = current_resume_metadata(str(vault))
            self.assertTrue(metadata["configured"])
            self.assertEqual(metadata["original_name"], source.name)
            self.assertEqual(
                metadata["sha256"],
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )
            self.assertEqual(resolve_current_resume(str(vault)), imported)

    def test_manifest_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "resume.docx"
            source.write_bytes(b"original")
            vault = root / "vault"
            imported = import_resume(str(source), str(vault))
            imported.write_bytes(b"tampered")

            with self.assertRaises(ValueError):
                resolve_current_resume(str(vault))

    def test_missing_vault_reports_not_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = current_resume_metadata(str(Path(tmp) / "missing"))
            self.assertEqual(metadata, {"configured": False})


if __name__ == "__main__":
    unittest.main()
