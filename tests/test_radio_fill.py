import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from application_forms import FillPlan
from browser_form_runtime import apply_fill_plan


class FakeOption:
    def __init__(self, value, option_id, label):
        self.value = value
        self.option_id = option_id
        self.label = label
        self.checked = False

    def get_attribute(self, name):
        if name == "value":
            return self.value
        if name == "id":
            return self.option_id
        if name == "type":
            return "radio"
        return None

    def check(self, force=False, timeout=0):
        self.checked = True

    def click(self, force=False, timeout=0):
        self.checked = True

    def is_checked(self):
        return self.checked


class FakeOptions:
    def __init__(self, options):
        self.options = options

    def count(self):
        return len(self.options)

    def nth(self, index):
        return self.options[index]


class FakeTarget:
    def __init__(self):
        self.first = self

    def count(self):
        return 1

    def evaluate(self, script):
        return "input"

    def get_attribute(self, name):
        if name == "type":
            return "radio"
        return None


class FakeLabel:
    def __init__(self, text):
        self.first = self
        self.text = text

    def count(self):
        return 1

    def inner_text(self, timeout=0):
        return self.text

    def click(self, force=False, timeout=0):
        pass


class FakePage:
    def __init__(self):
        self.yes = FakeOption("Yes", "yes-id", "Yes")
        self.no = FakeOption("No", "no-id", "No")
        self.target = FakeTarget()

    def locator(self, selector):
        if selector.startswith('[name="saas_question"]'):
            return self.target
        if selector == 'input[type="radio"][name="saas_question"]':
            return FakeOptions([self.yes, self.no])
        if selector == 'label[for="yes-id"]':
            return FakeLabel("Yes")
        if selector == 'label[for="no-id"]':
            return FakeLabel("No")
        raise AssertionError(selector)


class RadioFillTests(unittest.TestCase):
    def test_yes_radio_is_verified_as_checked(self):
        page = FakePage()
        plan = FillPlan(
            values={"saas_question": "Yes"},
            can_fill=True,
            reasons=("live_submission_disabled",),
        )
        reasons = apply_fill_plan(page, plan)
        self.assertTrue(page.yes.checked)
        self.assertFalse(page.no.checked)
        self.assertFalse(any(reason.startswith("radio_") for reason in reasons))


if __name__ == "__main__":
    unittest.main()
