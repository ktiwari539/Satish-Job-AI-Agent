from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from browser_form_runtime import inspect_page_fields


@dataclass(frozen=True)
class ApplicationEntryInspection:
    application_type: str
    button_text: str = ""
    button_selector: str = ""
    target_url: str = ""
    resolved_target_url: str = ""
    ats_provider: str = ""
    application_state: str = ""
    application_entry_clicked: bool = False
    opened: bool = False
    field_count: int = 0
    required_field_count: int = 0
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


def resolve_linkedin_external_url(target_url: str) -> str:
    if not target_url:
        return ""
    parsed = urlparse(target_url)
    if parsed.netloc.endswith("linkedin.com") and parsed.path.startswith("/safety/go/"):
        values = parse_qs(parsed.query).get("url", ())
        if values:
            return unquote(values[0]).strip()
    return target_url.strip()


def classify_ats_provider(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "bamboohr.com" in host:
        return "bamboohr"
    if "applytojob.com" in host:
        return "applytojob"
    if "greenhouse.io" in host or "greenhouse.com" in host:
        return "greenhouse"
    if "lever.co" in host:
        return "lever"
    if "myworkdayjobs.com" in host or "workday.com" in host:
        return "workday"
    if "ashbyhq.com" in host:
        return "ashby"
    return "unknown"


def _application_entry_selectors(provider: str) -> tuple[str, ...]:
    provider_selectors = {
        "bamboohr": (
            "a:has-text('Apply for this job')",
            "button:has-text('Apply for this job')",
            "a:has-text('Apply Now')",
            "button:has-text('Apply Now')",
        ),
        "greenhouse": (
            "a:has-text('Apply for this job')",
            "button:has-text('Apply for this job')",
        ),
        "lever": (
            "a:has-text('Apply for this job')",
            "a:has-text('Apply now')",
        ),
    }
    generic = (
        "a:has-text('Start Application')",
        "button:has-text('Start Application')",
        "a:has-text('Apply Now')",
        "button:has-text('Apply Now')",
        "a:has-text('Apply for this job')",
        "button:has-text('Apply for this job')",
    )
    return tuple(dict.fromkeys((*provider_selectors.get(provider, ()), *generic)))


def _inspect_external_form(page, provider: str):
    fields = inspect_page_fields(page)
    if fields:
        return fields, False, "FORM_READY", ""

    entry, _ = _first_visible(page, _application_entry_selectors(provider))
    if entry is None:
        return (), False, "APPLICATION_ENTRY_NOT_FOUND", "application_form_or_entry_not_detected"

    try:
        entry.click(timeout=5000)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            page.wait_for_timeout(1200)
        fields = inspect_page_fields(page)
    except Exception as exc:
        return (), False, "APPLICATION_ENTRY_FAILED", f"application_entry_open_failed:{type(exc).__name__}"

    if fields:
        return fields, True, "FORM_READY", ""
    return (), True, "FORM_NOT_READY", "application_entry_clicked_but_form_not_detected"


def _field_summary(fields):
    required = tuple(f.label for f in fields if f.required)
    return len(fields), len(required), required


def inspect_linkedin_application_entry(
    page,
    open_easy_apply: bool = False,
    open_external_apply: bool = False,
) -> ApplicationEntryInspection:
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
                application_state="APPLICATION_ENTRY_FOUND",
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
                application_state="APPLICATION_ENTRY_FAILED",
                opened=False,
                url=page.url,
                reason=f"easy_apply_open_failed:{type(exc).__name__}",
            )

        fields = inspect_page_fields(page)
        field_count, required_field_count, required_fields = _field_summary(fields)
        return ApplicationEntryInspection(
            application_type="LINKEDIN_EASY_APPLY",
            button_text=text,
            button_selector=selector,
            application_state="FORM_READY" if fields else "FORM_NOT_READY",
            application_entry_clicked=True,
            opened=True,
            field_count=field_count,
            required_field_count=required_field_count,
            required_fields=required_fields,
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
        resolved_target_url = resolve_linkedin_external_url(target_url)
        provider = classify_ats_provider(resolved_target_url)

        if not open_external_apply or not resolved_target_url:
            return ApplicationEntryInspection(
                application_type="EXTERNAL_APPLY",
                button_text=text,
                button_selector=selector,
                target_url=target_url,
                resolved_target_url=resolved_target_url,
                ats_provider=provider,
                application_state="APPLICATION_ENTRY_FOUND",
                opened=False,
                url=page.url,
            )

        try:
            page.goto(resolved_target_url, wait_until="domcontentloaded")
            fields, clicked, state, reason = _inspect_external_form(page, provider)
            field_count, required_field_count, required_fields = _field_summary(fields)
            return ApplicationEntryInspection(
                application_type="EXTERNAL_APPLY",
                button_text=text,
                button_selector=selector,
                target_url=target_url,
                resolved_target_url=resolved_target_url,
                ats_provider=provider,
                application_state=state,
                application_entry_clicked=clicked,
                opened=True,
                field_count=field_count,
                required_field_count=required_field_count,
                required_fields=required_fields,
                url=page.url,
                reason=reason,
            )
        except Exception as exc:
            return ApplicationEntryInspection(
                application_type="EXTERNAL_APPLY",
                button_text=text,
                button_selector=selector,
                target_url=target_url,
                resolved_target_url=resolved_target_url,
                ats_provider=provider,
                application_state="APPLICATION_PAGE_OPEN_FAILED",
                opened=False,
                url=page.url,
                reason=f"external_apply_open_failed:{type(exc).__name__}",
            )

    return ApplicationEntryInspection(
        application_type="NO_APPLY_ENTRY_FOUND",
        application_state="APPLICATION_ENTRY_NOT_FOUND",
        url=page.url,
        reason="apply_button_not_detected",
    )
