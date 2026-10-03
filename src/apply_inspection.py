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
    diagnostic_actions: tuple[str, ...] = ()


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
    if "rippling.com" in host:
        return "rippling"
    if "greythr.com" in host:
        return "greythr"
    return "unknown"


def _application_entry_selectors(provider: str) -> tuple[str, ...]:
    provider_selectors = {
        "bamboohr": (
            "a[href*='/application']",
            "a[href*='/apply']",
            "a:has-text('Apply for this job')",
            "button:has-text('Apply for this job')",
            "a:has-text('Apply Now')",
            "button:has-text('Apply Now')",
            "button:has-text('Apply')",
            "[role='button']:has-text('Apply')",
        ),
        "greenhouse": (
            "a:has-text('Apply for this job')",
            "button:has-text('Apply for this job')",
        ),
        "lever": (
            "a:has-text('Apply for this job')",
            "a:has-text('Apply now')",
        ),
        "greythr": (
            "a:has-text('Apply')",
            "button:has-text('Apply')",
            "a:has-text('Apply Now')",
            "button:has-text('Apply Now')",
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


def _looks_like_application_form(fields) -> bool:
    if not fields:
        return False
    tokens = " ".join(
        f"{f.key} {f.label} {f.field_type}".lower()
        for f in fields
    )
    strong_markers = ("resume", "cv", "cover letter", "linkedin", "first name", "last name")
    identity_markers = ("email", "phone", "mobile", "name")
    strong_hits = sum(marker in tokens for marker in strong_markers)
    identity_hits = sum(marker in tokens for marker in identity_markers)
    return strong_hits >= 1 or identity_hits >= 2


def _visible_apply_actions(page) -> tuple[str, ...]:
    script = """
    () => Array.from(document.querySelectorAll('a, button, [role="button"]'))
      .filter((el) => {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
      })
      .map((el) => (el.innerText || el.textContent || el.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim())
      .filter((text) => /apply|start|continue|candidate|job/i.test(text))
      .filter(Boolean)
      .slice(0, 12)
    """
    try:
        values = page.evaluate(script) or []
    except Exception:
        values = []
    return tuple(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))



def _candidate_application_urls(provider: str, current_url: str) -> tuple[str, ...]:
    parsed = urlparse(current_url)
    if not parsed.scheme or not parsed.netloc:
        return ()

    path = parsed.path.rstrip("/")
    candidates: list[str] = []

    if provider == "bamboohr" and "/careers/" in path:
        candidates.extend(
            (
                f"{parsed.scheme}://{parsed.netloc}{path}/application",
                f"{parsed.scheme}://{parsed.netloc}{path}/apply",
            )
        )
    elif provider == "greythr" and "/hire/jobs/" in path:
        candidates.extend(
            (
                f"{parsed.scheme}://{parsed.netloc}{path}/apply",
                f"{parsed.scheme}://{parsed.netloc}{path}/application",
            )
        )

    return tuple(dict.fromkeys(candidates))


def _probe_application_routes(page, provider: str):
    original_url = page.url
    diagnostics: list[str] = []

    for candidate in _candidate_application_urls(provider, original_url):
        diagnostics.append(f"route_probe:{candidate}")
        try:
            page.goto(candidate, wait_until="domcontentloaded")
            fields = inspect_page_fields(page)
            if _looks_like_application_form(fields):
                return fields, candidate, tuple(diagnostics)
        except Exception:
            continue

    if page.url != original_url:
        try:
            page.goto(original_url, wait_until="domcontentloaded")
        except Exception:
            pass

    return (), "", tuple(diagnostics)


def _inspect_external_form(page, provider: str):
    fields = inspect_page_fields(page)
    if _looks_like_application_form(fields):
        return fields, False, "FORM_READY", "", ()

    entry, _ = _first_visible(page, _application_entry_selectors(provider))
    if entry is None:
        route_fields, route_url, route_diagnostics = _probe_application_routes(page, provider)
        if _looks_like_application_form(route_fields):
            return route_fields, False, "FORM_READY", "", route_diagnostics
        diagnostics = tuple(dict.fromkeys((*_visible_apply_actions(page), *route_diagnostics)))
        return (), False, "APPLICATION_ENTRY_NOT_FOUND", "application_form_or_entry_not_detected", diagnostics

    try:
        entry.click(timeout=5000)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            page.wait_for_timeout(1200)
        fields = inspect_page_fields(page)
    except Exception as exc:
        return (), False, "APPLICATION_ENTRY_FAILED", f"application_entry_open_failed:{type(exc).__name__}", ()

    if _looks_like_application_form(fields):
        return fields, True, "FORM_READY", "", ()
    diagnostics = _visible_apply_actions(page)
    return (), True, "FORM_NOT_READY", "application_entry_clicked_but_form_not_detected", diagnostics


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
            if provider == "rippling":
                intended = urlparse(resolved_target_url).path.lower()
                actual = urlparse(page.url).path.lower()
                if "/apply" in intended and "/apply" not in actual:
                    return ApplicationEntryInspection(
                        application_type="EXTERNAL_APPLY",
                        button_text=text,
                        button_selector=selector,
                        target_url=target_url,
                        resolved_target_url=resolved_target_url,
                        ats_provider=provider,
                        application_state="APPLICATION_REDIRECTED_AWAY",
                        opened=True,
                        url=page.url,
                        reason="application_target_redirected_away_from_apply_flow",
                        diagnostic_actions=_visible_apply_actions(page),
                    )

            fields, clicked, state, reason, diagnostics = _inspect_external_form(page, provider)
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
                diagnostic_actions=diagnostics,
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
