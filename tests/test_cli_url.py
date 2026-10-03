import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from browser_qa import normalize_cli_url


class CliUrlTests(unittest.TestCase):
    def test_markdown_url_is_normalized(self):
        value = "[https://www.linkedin.com/jobs/view/123/](https://www.linkedin.com/jobs/view/123/)"
        self.assertEqual(
            normalize_cli_url(value),
            "https://www.linkedin.com/jobs/view/123/",
        )

    def test_plain_url_is_unchanged(self):
        value = "https://www.linkedin.com/jobs/view/123/"
        self.assertEqual(normalize_cli_url(value), value)


if __name__ == "__main__":
    unittest.main()
