import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from apply_inspection import (
    classify_ats_provider,
    inspect_linkedin_application_entry,
    resolve_linkedin_external_url,
)


class FakeButton:
    def __init__(self, text, visible=True):
        self.text = text
        self.visible = visible
        self.clicked = False

    def count(self):
        return 1

    def is_visible(self):
        return self.visible

    def inner_text(self, timeout=0):
        return self.text

    def click(self, timeout=0):
        self.clicked = True


class EmptyLocator:
    @property
    def first(self):
        return self

    def count(self):
        return 0

    def is_visible(self):
        return False


class ButtonLocator:
    def __init__(self, button):
        self.button = button

    @property
    def first(self):
        return self.button


class FakePage:
    def __init__(self, selectors):
        self.selectors = selectors
        self.url = "https://www.linkedin.com/jobs/view/123/"
        self.waited = False

    def locator(self, selector):
        button = self.selectors.get(selector)
        return ButtonLocator(button) if button else EmptyLocator()

    def wait_for_timeout(self, value):
        self.waited = True


class ApplyInspectionTests(unittest.TestCase):
    def test_detects_easy_apply_without_clicking(self):
        button = FakeButton("Easy Apply")
        page = FakePage({"button.jobs-apply-button": button})
        result = inspect_linkedin_application_entry(page, open_easy_apply=False)
        self.assertEqual(result.application_type, "LINKEDIN_EASY_APPLY")
        self.assertFalse(result.opened)
        self.assertFalse(button.clicked)

    def test_external_apply_is_not_opened(self):
        button = FakeButton("Apply")
        page = FakePage({"a.jobs-apply-button": button})
        result = inspect_linkedin_application_entry(page, open_easy_apply=True)
        self.assertEqual(result.application_type, "EXTERNAL_APPLY")
        self.assertFalse(result.opened)
        self.assertFalse(button.clicked)

    def test_resolves_linkedin_safety_wrapper(self):
        wrapped = (
            "https://www.linkedin.com/safety/go/?url="
            "https%3A%2F%2Fzerofox.bamboohr.com%2Fcareers%2F250"
        )
        resolved = resolve_linkedin_external_url(wrapped)
        self.assertEqual(resolved, "https://zerofox.bamboohr.com/careers/250")
        self.assertEqual(classify_ats_provider(resolved), "bamboohr")

    def test_classifies_applytojob(self):
        self.assertEqual(
            classify_ats_provider("https://hackerearth.applytojob.com/apply/abc"),
            "applytojob",
        )

    def test_missing_apply_fails_closed(self):
        page = FakePage({})
        result = inspect_linkedin_application_entry(page)
        self.assertEqual(result.application_type, "NO_APPLY_ENTRY_FOUND")


if __name__ == "__main__":
    unittest.main()
