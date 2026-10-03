from dataclasses import dataclass, asdict
from typing import Optional

from browser_form_runtime import inspect_page_fields


@dataclass(frozen=True)
class ApplicationEntryInspection:
    application_type: str
    button_text: str = ""
    button_selector: str = ""
    target_url: str = ""
    opened: bool = False
    field_count: int = 0
    required_fields: tuple[str, ...] = ()
    url: str = ""
    reason: str = ""


def _first_visible(page, selectors: tuple[str, ...]):
    for selector in selectors:
        try:
            target = page.locator(selector).first
            if target.count() and target.is_visible():
                return target, selector
        except Exception:
            continue
    return None, ""


def inspect_linkedin_application_entry(page, open_easy_apply: bool = False) -> ApplicationEntryInspection:
    easy_selectors = (
        "button.jobs-apply-button",
        "button[aria-label*='Easy Apply']",
        "button:has-text('Easy Apply')",
    )
    external_selectors = (
        "a.jobs-apply-button",
        "a:has-text('Apply')",
        "button:has-text('Apply on company website')",
    )

    button, selector = _first_visible(page, easy_selectors)
    if button is not None:
        try:
            text = button.inner_text(timeout=1500).strip()
        except Exception:
            text = "Easy Apply"

        if not open_easy_apply:
            return ApplicationEntryInspection(
                application_type="LINKEDIN_EASY_APPLY",
                button_text=text,
                button_selector=selector,
                opened=False,
                url=page.url,
            )

        try:
            button.click(timeout=5000)
            page.wait_for_timeout(800)
        except Exception as exc:
            return ApplicationEntryInspection(
                application_type="LINKEDIN_EASY_APPLY",
                button_text=text,
                button_selector=selector,
                opened=False,
                url=page.url,
                reason=f"easy_apply_open_failed:{type(exc).__name__}",
            )

        fields = inspect_page_fields(page)
        return ApplicationEntryInspection(
            application_type="LINKEDIN_EASY_APPLY",
            button_text=text,
            button_selector=selector,
            opened=True,
            field_count=len(fields),
            required_fields=tuple(f.label for f in fields if f.required),
            url=page.url,
        )

    button, selector = _first_visible(page, external_selectors)
    if button is not None:
        try:
            text = button.inner_text(timeout=1500).strip()
        except Exception:
            text = "Apply"
        try:
            target_url = (button.get_attribute("href", timeout=1500) or "").strip()
        except Exception:
            target_url = ""
        return ApplicationEntryInspection(
            application_type="EXTERNAL_APPLY",
            button_text=text,
            button_selector=selector,
            target_url=target_url,
            opened=False,
            url=page.url,
        )

    return ApplicationEntryInspection(
        application_type="NO_APPLY_ENTRY_FOUND",
        url=page.url,
        reason="apply_button_not_detected",
    )
