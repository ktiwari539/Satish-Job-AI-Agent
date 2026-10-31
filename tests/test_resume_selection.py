"""A transient matching readback must never authorize wizard progression."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from resume_selection import prepare_resume_picker


class ResumeSelectionTests(unittest.TestCase):
    def test_every_matching_readback_reverted_by_the_page_stays_blocked(self):
        page = MagicMock()
        with tempfile.TemporaryDirectory() as folder:
            resume = Path(folder) / 'fixture.pdf'
            resume.write_bytes(b'%PDF-1.4 fixture')
            snapshots = ['different_resume_selected'] + [
                state for _ in range(10)
                for state in ('matching_resume_selected', 'different_resume_selected')]
            with patch('resume_selection._probe', return_value=dict(
                    picker=True, status='selection_prepared', choice_keys=['document'])), \
                 patch('resume_selection.inspect_resume_evidence', side_effect=snapshots):
                result = prepare_resume_picker(page, str(resume))
        self.assertFalse(result.may_advance)
        self.assertEqual(result.state, 'different_resume_selected')
        self.assertEqual(result.reason, 'configured_resume_selection_unverified')
        page.locator.return_value.click.assert_called_once()
        page.locator.return_value.set_input_files.assert_not_called()


if __name__ == '__main__':
    unittest.main()
