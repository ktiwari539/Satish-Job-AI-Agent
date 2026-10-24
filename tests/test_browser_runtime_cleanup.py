"""Playwright cleanup must preserve debug results after driver interruption."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from browser_runtime import PlaywrightSession


class BrowserRuntimeCleanupTests(unittest.TestCase):
    def test_driver_disconnect_during_context_close_is_not_reported_as_new_failure(self):
        session = PlaywrightSession()
        session.context = MagicMock()
        session._pw = MagicMock()
        session.context.close.side_effect = Exception(
            "BrowserContext.close: Connection closed while reading from the driver"
        )
        self.assertFalse(session.__exit__(None, None, None))
        session._pw.stop.assert_called_once()

    def test_other_cleanup_failure_is_not_silenced(self):
        session = PlaywrightSession()
        session.context = MagicMock()
        session._pw = MagicMock()
        session.context.close.side_effect = RuntimeError("unexpected browser error")
        with self.assertRaisesRegex(RuntimeError, "unexpected browser error"):
            session.__exit__(None, None, None)
        session._pw.stop.assert_called_once()

    def test_original_exception_is_not_masked_by_cleanup(self):
        session = PlaywrightSession()
        session.context = MagicMock()
        session._pw = MagicMock()
        session.context.close.side_effect = RuntimeError("unexpected browser error")
        self.assertFalse(session.__exit__(KeyboardInterrupt, KeyboardInterrupt(), None))
        session._pw.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
