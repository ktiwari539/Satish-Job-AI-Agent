from dataclasses import dataclass
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from agent_trace import trace_event, trace_step
from browser_form_runtime import inspect_page_fields
from navigation import bounded_goto


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
            matches = page.locator(selector)
            count = min(matches.count(), 12)
            for index in range(count):
                target = matches.nth(index)
                if target.is_visible():
                    return target, selector
        except Exception:
            continue
    return None, ""


def _wait_for_first_visible(
    page,
    selectors: tuple[str, ...],
    timeout_ms: int = 6000,
    interval_ms: int = 250,
):
    """Wait for LinkedIn's client-rendered apply control instead of racing DOMContentLoaded."""
    elapsed = 0
    while True:
        target, selector = _first_visible(page, selectors)
        if target is not None:
            return target, selector
        if elapsed >= timeout_ms:
            return None, ""
        page.wait_for_timeout(interval_ms)
        elapsed += interval_ms


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
    if "keka.com" in host:
        return "keka"
    if "smartrecruiters.com" in host:
        return "smartrecruiters"
    if "n8n.cloud" in host:
        return "n8n_custom"
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
        "a:has-text('Apply for this role')",
        "button:has-text('Apply for this role')",
        "[role='button']:has-text('Apply for this role')",
        "a:has-text('Start Application')",
        "button:has-text('Start Application')",
        "a:has-text('Apply Now')",
        "button:has-text('Apply Now')",
        "a:has-text('Apply for this job')",
        "button:has-text('Apply for this job')",
        "[role='button']:has-text('Apply Now')",
        "input[type='button'][value*='Apply']",
        "input[type='button'][value*='APPLY']",
        "input[type='submit'][value*='Apply']",
        "input[type='submit'][value*='APPLY']",
        "[onclick]:has-text('Apply Now')",
        "[onclick]:has-text('APPLY NOW')",
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
            bounded_goto(page, candidate)
            fields = inspect_page_fields(page)
            if _looks_like_application_form(fields):
                return fields, candidate, tuple(diagnostics)
        except Exception:
            continue

    if page.url != original_url:
        try:
            bounded_goto(page, original_url)
        except Exception:
            pass

    return (), "", tuple(diagnostics)


def _wait_for_external_form_fields(page, timeout_ms: int = 8000, interval_ms: int = 400):
    elapsed = 0
    while elapsed <= timeout_ms:
        try:
            fields = inspect_page_fields(page)
        except Exception:
            fields = ()
        if _looks_like_application_form(fields):
            return fields
        if elapsed >= timeout_ms:
            break
        try:
            page.wait_for_timeout(interval_ms)
        except Exception:
            break
        elapsed += interval_ms
    return ()


def _visible_entry_candidates(page, selectors: tuple[str, ...], limit: int = 8):
    candidates = []
    seen = set()
    for selector in selectors:
        try:
            matches = page.locator(selector)
            count = min(matches.count(), 12)
        except Exception:
            continue
        for index in range(count):
            if len(candidates) >= limit:
                return tuple(candidates)
            try:
                target = matches.nth(index)
                if not target.is_visible():
                    continue
                try:
                    text = target.inner_text(timeout=1000).strip()
                except Exception:
                    text = ""
                try:
                    href = (target.get_attribute("href", timeout=1000) or "").strip()
                except Exception:
                    href = ""
                signature = (selector, text, href)
                if signature in seen:
                    continue
                seen.add(signature)
                candidates.append((target, selector, text, href))
            except Exception:
                continue
    return tuple(candidates)


def _popup_destination(page, before_pages) -> str:
    try:
        after_pages = list(page.context.pages)
    except Exception:
        return ""
    new_pages = [candidate for candidate in after_pages if candidate not in before_pages]
    if not new_pages:
        return ""
    popup = new_pages[-1]
    try:
        popup.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    try:
        destination = str(popup.url or "")
    except Exception:
        destination = ""
    if destination and destination != "about:blank":
        try:
            popup.close()
        except Exception:
            pass
        return destination
    return ""


def _open_external_entry(page, entry, *, text: str = "", href: str = ""):
    before_url = str(getattr(page, "url", "") or "")
    try:
        before_pages = list(page.context.pages)
    except Exception:
        before_pages = []

    try:
        entry.click(timeout=5000)
    except Exception as exc:
        return False, f"entry_click_failed:{type(exc).__name__}"

    try:
        page.wait_for_timeout(700)
    except Exception:
        pass

    current_url = str(getattr(page, "url", "") or "")
    if current_url and current_url != before_url:
        return True, f"entry_navigated:{current_url}"

    popup_url = _popup_destination(page, before_pages)
    if popup_url:
        try:
            bounded_goto(page, popup_url)
            return True, f"entry_popup_navigated:{popup_url}"
        except Exception as exc:
            return False, f"popup_navigation_failed:{type(exc).__name__}"

    clean_href = str(href or "").strip()
    if clean_href and not clean_href.lower().startswith(("javascript:", "#")):
        destination = urljoin(before_url, clean_href)
        if destination and destination != before_url:
            try:
                bounded_goto(page, destination)
                return True, f"entry_href_navigated:{destination}"
            except Exception as exc:
                return False, f"href_navigation_failed:{type(exc).__name__}"

    return True, f"entry_clicked_no_navigation:{text or 'apply'}"


def _inspect_external_form(page, provider: str):
    fields = inspect_page_fields(page)
    if _looks_like_application_form(fields):
        return fields, False, "FORM_READY", "", ()

    selectors = _application_entry_selectors(provider)
    candidates = _visible_entry_candidates(page, selectors)
    if not candidates:
        route_fields, route_url, route_diagnostics = _probe_application_routes(page, provider)
        if _looks_like_application_form(route_fields):
            return route_fields, False, "FORM_READY", "", route_diagnostics
        diagnostics = tuple(dict.fromkeys((*_visible_apply_actions(page), *route_diagnostics)))
        return (), False, "APPLICATION_ENTRY_NOT_FOUND", "application_form_or_entry_not_detected", diagnostics

    diagnostics = []
    original_url = str(getattr(page, "url", "") or "")
    clicked_any = False

    for entry, selector, text, href in candidates:
        before_url = str(getattr(page, "url", "") or "")
        opened, action = _open_external_entry(page, entry, text=text, href=href)
        diagnostics.append(f"{selector}:{text or 'apply'}:{action}")
        clicked_any = clicked_any or opened
        if not opened:
            continue

        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        fields = _wait_for_external_form_fields(page, timeout_ms=5000)
        if _looks_like_application_form(fields):
            return fields, True, "FORM_READY", "", tuple(diagnostics)

        after_url = str(getattr(page, "url", "") or "")
        if after_url != before_url:
            # The first destination can itself be a landing page. Try one
            # additional visible Apply control there before giving up.
            nested = _visible_entry_candidates(page, selectors, limit=4)
            for nested_entry, nested_selector, nested_text, nested_href in nested:
                nested_opened, nested_action = _open_external_entry(
                    page,
                    nested_entry,
                    text=nested_text,
                    href=nested_href,
                )
                diagnostics.append(
                    f"{nested_selector}:{nested_text or 'apply'}:{nested_action}"
                )
                clicked_any = clicked_any or nested_opened
                if not nested_opened:
                    continue
                fields = _wait_for_external_form_fields(page, timeout_ms=5000)
                if _looks_like_application_form(fields):
                    return fields, True, "FORM_READY", "", tuple(diagnostics)

            # Restore the original landing page so another candidate can be tried.
            if original_url and str(getattr(page, "url", "") or "") != original_url:
                try:
                    bounded_goto(page, original_url)
                except Exception:
                    pass

    visible = _visible_apply_actions(page)
    diagnostics = tuple(dict.fromkeys((*diagnostics, *visible)))
    return (
        (),
        clicked_any,
        "FORM_NOT_READY",
        "application_entry_clicked_but_form_not_detected",
        diagnostics,
    )


def _field_summary(fields):
    required = tuple(f.label for f in fields if f.required)
    return len(fields), len(required), required


_EASY_APPLY_MODAL_SELECTORS = (
    ".jobs-easy-apply-modal",
    # LinkedIn sometimes omits role='dialog' from its Artdeco modal.
    ".artdeco-modal",
    "[role='dialog']",
)


def _visible_easy_apply_modal(page):
    """Require an actual visible dialog, not unrelated job-page fields."""
    return _first_visible(page, _EASY_APPLY_MODAL_SELECTORS)[0]


def _wait_for_easy_apply_modal(page, timeout_ms=3000, interval_ms=250):
    elapsed = 0
    while True:
        modal = _visible_easy_apply_modal(page)
        if modal is not None:
            return modal
        if elapsed >= timeout_ms:
            return None
        try:
            page.wait_for_timeout(interval_ms)
        except Exception:
            return None
        elapsed += interval_ms


def _verified_inline_easy_apply_wizard(page, *, job_url_before: str, fields=()) -> bool:
    """Verify a real LinkedIn Easy Apply wizard without a modal wrapper.

    Oct 22 browser trace: an actual 1/6 contact form exists with five
    required inputs, valid populated phone and enabled Next, yet there are
    zero conventional modal nodes. Require all these signals, the same
    exact LinkedIn job path, and no visible Submit control. Do not inspect
    or return any applicant-entered values.
    """
    before = urlparse(str(job_url_before or ""))
    after = urlparse(str(getattr(page, "url", "") or ""))
    if (
        before.scheme != "https"
        or after.scheme != "https"
        or before.hostname not in ("linkedin.com", "www.linkedin.com")
        or after.hostname not in ("linkedin.com", "www.linkedin.com")
        or before.path.rstrip("/") != after.path.rstrip("/")
        or re.fullmatch(r"/jobs/view/[0-9]{7,15}/?", before.path) is None
    ):
        return False
    # The standard field reader also recognizes required fields marked by
    # a star on their label or by CSS classes. Do not require native
    # input.required on every LinkedIn contact field.
    if len(fields) < 4 or sum(bool(f.required) for f in fields) < 3:
        return False
    if not any(
        f.field_type == "tel"
        or "phone" in (f"{f.key} {f.label}").casefold()
        or "mobile" in (f"{f.key} {f.label}").casefold()
        for f in fields
    ):
        return False
    script = r"""() => {
      const visible = (el) => {
        if (!el || !el.isConnected) return false;
        const r = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        return r.width > 0 && r.height > 0 &&
          st.display !== 'none' && st.visibility !== 'hidden';
      };
      const bodyText = String(document.body?.innerText || '');
      const m = bodyText.match(/\b(\d{1,2})\s*\/\s*(\d{1,2})\s*pages?\b/i);
      if (!m || Number(m[1]) !== 1 || Number(m[2]) < 2) return false;
      const inputs = Array.from(document.querySelectorAll(
        'input,textarea,select'
      )).filter(el => visible(el) && !el.disabled &&
        el.getAttribute('type') !== 'hidden');
      const required = inputs.filter(el =>
        el.required || el.getAttribute('aria-required') === 'true');
      if (inputs.length < 4) return false;
      const phone = inputs.filter(el => {
        const marker = [el.getAttribute('type'), el.getAttribute('name'),
                        el.getAttribute('id'), el.getAttribute('autocomplete')]
          .filter(Boolean).join(' ').toLowerCase();
        return /(phone|mobile|telephone|\btel\b)/.test(marker);
      });
      if (phone.length !== 1) return false;
      if (!String(phone[0].value || '').trim()) return false;
      if (phone[0].getAttribute('aria-invalid') === 'true' ||
          !phone[0].checkValidity()) return false;
      if (required.some(el => (
        el.getAttribute('aria-invalid') === 'true' ||
        !el.checkValidity()
      ))) return false;
      const buttons = Array.from(document.querySelectorAll(
        'button,[role="button"],input[type="button"],input[type="submit"]'
      )).filter(visible);
      const control = el => String(
        el.getAttribute('aria-label') ||
        el.innerText || el.textContent || el.value || ''
      ).replace(/\s+/g, ' ').trim().toLowerCase();
      const next = buttons.filter(el =>
        ['next','next step','continue','continue to next step']
          .includes(control(el)) &&
        !el.disabled && el.getAttribute('aria-disabled') !== 'true');
      const submit = buttons.some(el =>
        ['submit','submit application','send application']
          .includes(control(el)));
      return next.length === 1 && !submit;
    }"""
    try:
        return page.evaluate(script) is True
    except Exception:
        return False


def _wait_for_verified_easy_apply_surface(
    page, *, job_url_before: str, timeout_ms: int = 6000, interval_ms: int = 400
):
    """Observe an actual modal/inline contact wizard, never a bare Submit.

    LinkedIn can asynchronously attach the wizard after the CTA click. Keep
    polling bounded and avoid accepting background search or job-alert fields.
    """
    elapsed = 0
    while True:
        modal = _visible_easy_apply_modal(page)
        fields = inspect_page_fields(page)
        if modal is not None and fields:
            return modal, False, fields
        if modal is None and _verified_inline_easy_apply_wizard(
            page, job_url_before=job_url_before, fields=fields
        ):
            return None, True, fields
        if elapsed >= timeout_ms:
            return None, False, fields
        try:
            page.wait_for_timeout(interval_ms)
        except Exception:
            return None, False, fields
        elapsed += interval_ms


def _retry_safe_easy_apply_cta(page, button, signals: dict) -> bool:
    """Exactly one recovery click only if original UI is provably unchanged.

    No retry on navigation to a different job, newly rendered application
    surface, newly visible Submit, or loss of the original Easy Apply CTA.
    """
    if (
        signals.get("route_state") != "same_exact_job"
        or signals.get("observable_form_structure_changed") is not False
        or signals.get("wizard_progress_present") is True
        or signals.get("candidate_modal_count", 0) != 0
        or signals.get("visible_easy_apply_cta_count", 0) < 1
        or signals.get("preclick_visible_easy_apply_cta_count", 0) < 1
        or signals.get("visible_submit_count", -1)
           != signals.get("preclick_visible_submit_count", -2)
    ):
        return False
    try:
        if not button.is_visible():
            return False
        if hasattr(button, "is_enabled") and not button.is_enabled():
            return False
        button.click(timeout=2500)
        trace_event(
            "easy_apply_cta_recovery_clicked",
            recovery_clicks=1, verified_form_before_retry=False,
        )
        return True
    except Exception as exc:
        trace_event(
            "easy_apply_cta_recovery_failed", error_type=type(exc).__name__,
        )
        return False


def _safe_browser_page_count(page):
    try:
        return min(len(page.context.pages), 30)
    except Exception:
        return 0


def _post_click_route_state(url_before: str, url_after: str) -> str:
    """Report only the verified route relation; never log URL query strings."""
    before, after = urlparse(url_before), urlparse(url_after)
    if (
        before.scheme != "https"
        or before.hostname not in ("linkedin.com", "www.linkedin.com")
        or re.fullmatch(r"/jobs/view/[0-9]{7,15}/?", before.path) is None
    ):
        return "unverified_route"
    if after.scheme != "https" or after.hostname not in ("linkedin.com", "www.linkedin.com"):
        return "left_linkedin"
    if after.path.rstrip("/") == before.path.rstrip("/"):
        return "same_exact_job"
    if re.fullmatch(r"/jobs/view/[0-9]{7,15}/?", after.path):
        return "different_linkedin_job"
    return "different_linkedin_route"


def _post_click_easy_apply_probe(page, *, url_before, pages_before, baseline=None, emit_trace=True):
    """Only structural evidence. Never export URL parameters or input values."""
    script = r"""() => {
      const visible = el => {
        if (!el || !el.isConnected) return false;
        const rect = el.getBoundingClientRect(), s = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 &&
          s.display !== 'none' && s.visibility !== 'hidden';
      };
      const controlLabel = el => String(
        el.getAttribute('aria-label') || el.innerText ||
        el.textContent || el.value || ''
      ).replace(/\s+/g, ' ').trim().toLowerCase();
      const controls = Array.from(document.querySelectorAll(
        'button,[role="button"],input[type="button"],input[type="submit"]'
      )).filter(visible);
      const submit = controls.filter(el =>
        ['submit', 'submit application', 'send application']
          .includes(controlLabel(el)));
      const applicationRoot = el => el.closest(
        '.jobs-easy-apply-modal, .artdeco-modal, [role="dialog"], ' +
        '.jobs-easy-apply-content, .jobs-easy-apply-form-section__grouping, ' +
        '[class*="jobs-easy-apply-form"], [data-test*="easy-apply"]'
      );
      const associatedSubmit = submit.filter(el => Boolean(applicationRoot(el)));
      const contactRoot = associatedSubmit.find(el => {
        const root = applicationRoot(el);
        if (!root || !visible(root)) return false;
        const fields = Array.from(root.querySelectorAll('input,select,textarea'))
          .filter(visible);
        const hasContact = kind => fields.some(field => {
          const signature = [
            field.name, field.id, field.type, field.autocomplete
          ].filter(Boolean).join(' ').toLowerCase();
          return kind.test(signature);
        });
        return fields.length >= 2 &&
          hasContact(/email/) && hasContact(/phone|mobile|tel/);
      });
      const easyApply = controls.filter(el =>
        ['easy apply', 'continue applying'].includes(controlLabel(el)));
      const next = controls.filter(el =>
        ['next', 'next step', 'continue', 'continue to next step']
          .includes(controlLabel(el)) &&
          !el.disabled && el.getAttribute('aria-disabled') !== 'true');
      const progress = String(document.body?.innerText || '').match(
        /\b(\d{1,2})\s*\/\s*(\d{1,2})\s*pages?\b/i
      );
      return {
        iframe_count: document.querySelectorAll('iframe').length,
        candidate_modal_count: document.querySelectorAll(
          '.jobs-easy-apply-modal,.artdeco-modal,[role="dialog"]'
        ).length,
        main_document_input_count: document.querySelectorAll(
          'input,select,textarea'
        ).length,
        visible_form_count: Array.from(document.querySelectorAll('form'))
          .filter(visible).length,
        visible_easy_apply_cta_count: easyApply.length,
        visible_submit_count: submit.length,
        submit_with_form_count: submit.filter(el => Boolean(el.closest('form'))).length,
        submit_in_job_alert_count: submit.filter(el => Boolean(el.closest(
          '[class*="job-alert"],[class*="jobAlert"],' +
          '[data-test*="job-alert"],[class*="create-alert"]'
        ))).length,
        submit_in_application_container_count: associatedSubmit.length,
        submit_container_has_contact_fields: Boolean(contactRoot),
        enabled_next_count: next.length,
        wizard_progress_present: Boolean(progress),
        wizard_final_page: Boolean(progress && Number(progress[1]) >= 2 &&
                                   Number(progress[1]) === Number(progress[2])),
        page_hidden: document.hidden
      };
    }"""
    try:
        raw = page.evaluate(script)
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    after_url = str(getattr(page, "url", "") or "")
    data = {
        "url_changed": after_url != str(url_before or ""),
        "route_state": _post_click_route_state(str(url_before or ""), after_url),
        "new_browser_pages": max(0, _safe_browser_page_count(page) - pages_before),
        "page_hidden": raw.get("page_hidden") is True,
        "wizard_progress_present": raw.get("wizard_progress_present") is True,
        "wizard_final_page": raw.get("wizard_final_page") is True,
        "submit_container_has_contact_fields": (
            raw.get("submit_container_has_contact_fields") is True
        ),
    }
    for key in (
        "iframe_count", "candidate_modal_count", "main_document_input_count",
        "visible_submit_count", "enabled_next_count",
        "submit_with_form_count", "submit_in_application_container_count",
        "visible_form_count", "visible_easy_apply_cta_count",
        "submit_in_job_alert_count",
    ):
        number = raw.get(key)
        data[key] = min(max(number, 0), 1000) if type(number) is int else 0
    if isinstance(baseline, dict):
        compare_keys = (
            "candidate_modal_count", "main_document_input_count",
            "visible_form_count", "visible_submit_count", "enabled_next_count",
            "visible_easy_apply_cta_count",
            "submit_in_application_container_count",
        )
        data["preclick_visible_submit_count"] = baseline.get("visible_submit_count", 0)
        data["preclick_visible_easy_apply_cta_count"] = baseline.get(
            "visible_easy_apply_cta_count", 0
        )
        data["visible_submit_preexisting"] = (
            baseline.get("visible_submit_count", 0) > 0
        )
        data["observable_form_structure_changed"] = any(
            data.get(key) != baseline.get(key)
            for key in compare_keys
        )
        data["observed_input_count_delta"] = max(
            -1000, min(1000, data["main_document_input_count"] -
                        baseline.get("main_document_input_count", 0))
        )
    if emit_trace:
        trace_event("easy_apply_post_click_probe", **data)
    return data


def _post_click_unverified_reason(signals: dict) -> str:
    """Specific, conservative diagnosis; never upgrades to FORM_READY."""
    if signals.get("route_state") == "unverified_route":
        return "easy_apply_modal_not_opened"
    if signals.get("route_state") != "same_exact_job":
        return "easy_apply_unverified_navigation"
    if signals.get("visible_submit_count", 0) > 0:
        # Positive structural grouping can suggest a single-page form,
        # but never authorizes filling or clicking Submit.
        if (signals.get("submit_container_has_contact_fields") is True
                and signals.get("submit_in_application_container_count", 0) == 1):
            return "easy_apply_possible_single_step_form_unverified"
        if signals.get("submit_in_application_container_count", 0) == 0:
            return "easy_apply_unscoped_submit_control"
        return "easy_apply_submit_visible_without_verified_wizard"
    return "easy_apply_modal_not_opened"


def inspect_linkedin_application_entry(
    page,
    open_easy_apply: bool = False,
    open_external_apply: bool = False,
) -> ApplicationEntryInspection:
    trace_event(
        "application_entry_inspection_start",
        current_url=str(getattr(page, "url", "") or ""),
        open_easy_apply=open_easy_apply,
        open_external_apply=open_external_apply,
    )
    easy_selectors = (
        "button.jobs-apply-button",
        ".jobs-s-apply button.jobs-apply-button",
        "button[aria-label*='Easy Apply']",
        "button[aria-label*='Continue applying']",
        "button[aria-label='Continue']",
        "button:has-text('Easy Apply')",
        "button:has-text('Continue applying')",
        "button:text-is('Continue')",
    )
    external_selectors = (
        "a.jobs-apply-button",
        "a[aria-label*='Apply on company website']",
        "button[aria-label*='Apply on company website']",
        "a:text-is('Apply on company website')",
        "button:text-is('Apply on company website')",
    )

    # If a previous QA run left Easy Apply open, resume that visible form
    # instead of requiring the underlying job-page button to be present.
    dialog = _visible_easy_apply_modal(page)
    if dialog is not None:
        fields = inspect_page_fields(page)
        if fields:
            field_count, required_field_count, required_fields = _field_summary(fields)
            trace_event(
                "application_entry_reused_open_form",
                field_count=field_count,
                required_field_count=required_field_count,
            )
            return ApplicationEntryInspection(
                application_type="LINKEDIN_EASY_APPLY",
                application_state="FORM_READY",
                application_entry_clicked=False,
                opened=True,
                field_count=field_count,
                required_field_count=required_field_count,
                required_fields=required_fields,
                url=page.url,
                diagnostic_actions=("reused_open_easy_apply_form",),
            )

    # LinkedIn renders the apply CTA asynchronously after DOMContentLoaded.
    # Wait for it rather than immediately declaring APPLICATION_ENTRY_NOT_FOUND.
    button, selector = _wait_for_first_visible(page, easy_selectors)
    if button is not None:
        try:
            text = button.inner_text(timeout=1500).strip()
        except Exception:
            text = "Easy Apply"

        trace_event(
            "application_entry_detected",
            application_type="LINKEDIN_EASY_APPLY",
            button_text=text,
            selector=selector,
            will_open=open_easy_apply,
        )
        if not open_easy_apply:
            return ApplicationEntryInspection(
                application_type="LINKEDIN_EASY_APPLY",
                button_text=text,
                button_selector=selector,
                application_state="APPLICATION_ENTRY_FOUND",
                opened=False,
                url=page.url,
            )

        url_before = str(getattr(page, "url", "") or "")
        pages_before = _safe_browser_page_count(page)
        # This read-only baseline lets the eventual blocker event distinguish
        # a pre-existing page Submit from a newly rendered application Submit.
        # Never collect applicant input values, DOM text, or raw query strings.
        preclick_probe = _post_click_easy_apply_probe(
            page, url_before=url_before, pages_before=pages_before,
            emit_trace=False,
        )
        try:
            with trace_step("easy_apply_open", selector=selector, button_text=text):
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

        # The page may have search inputs, account preferences and other
        # background controls. These are not an Easy Apply form. Requiring
        # the modal prevents a false FORM_READY after clicking a CTA that
        # did not actually open the application.
        modal, verified_inline, fields = _wait_for_verified_easy_apply_surface(
            page, job_url_before=url_before,
        )
        recovery_clicks = 0
        if modal is None and not verified_inline:
            signals = _post_click_easy_apply_probe(
                page, url_before=url_before, pages_before=pages_before,
                baseline=preclick_probe,
            )
            if _retry_safe_easy_apply_cta(page, button, signals):
                recovery_clicks = 1
                modal, verified_inline, fields = _wait_for_verified_easy_apply_surface(
                    page, job_url_before=url_before, timeout_ms=5000,
                )
                if modal is None and not verified_inline:
                    signals = _post_click_easy_apply_probe(
                        page, url_before=url_before, pages_before=pages_before,
                        baseline=preclick_probe,
                    )

        if verified_inline:
            trace_event(
                "easy_apply_inline_wizard_verified",
                entry_clicked=True, entry_kind="inline_contact_wizard",
                recovery_clicks=recovery_clicks,
            )
        if modal is None and not verified_inline:
            blocker_reason = _post_click_unverified_reason(signals)
            trace_event(
                "easy_apply_form_still_unverified",
                reason=blocker_reason,
                button_clicked=True,
                recovery_clicks=recovery_clicks,
            )
            return ApplicationEntryInspection(
                application_type="LINKEDIN_EASY_APPLY",
                button_text=text,
                button_selector=selector,
                application_state="FORM_NOT_READY",
                application_entry_clicked=True,
                opened=False,
                url=page.url,
                reason=blocker_reason,
            )

        field_count, required_field_count, required_fields = _field_summary(fields)
        trace_event(
            "easy_apply_form_inspected",
            modal_detected=modal is not None,
            inline_wizard_verified=verified_inline,
            field_count=field_count,
            required_field_count=required_field_count,
            state="FORM_READY" if fields else "FORM_NOT_READY",
        )
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
            reason="" if fields else "easy_apply_modal_has_no_fields",
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
        trace_event(
            "application_entry_detected",
            application_type="EXTERNAL_APPLY",
            button_text=text,
            selector=selector,
            provider=provider,
            target_url=resolved_target_url,
            will_open=open_external_apply,
        )

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
            with trace_step(
                "external_apply_navigation",
                provider=provider,
                target_url=resolved_target_url,
            ):
                bounded_goto(page, resolved_target_url)
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

            with trace_step("external_form_inspection", provider=provider):
                fields, clicked, state, reason, diagnostics = _inspect_external_form(page, provider)
            field_count, required_field_count, required_fields = _field_summary(fields)
            trace_event(
                "external_form_result",
                provider=provider,
                state=state,
                reason=reason,
                clicked_entry=clicked,
                field_count=field_count,
                required_field_count=required_field_count,
                diagnostic_actions=list(diagnostics),
                current_url=str(getattr(page, "url", "") or ""),
            )
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

    try:
        body_text = page.locator("body").inner_text(timeout=2000).lower()
    except Exception:
        body_text = ""

    closed_markers = (
        "no longer accepting applications",
        "applications are closed",
        "this job is no longer available",
    )
    if any(marker in body_text for marker in closed_markers):
        trace_event("application_entry_result", state="APPLICATION_CLOSED")
        return ApplicationEntryInspection(
            application_type="NO_APPLY_ENTRY_FOUND",
            application_state="APPLICATION_CLOSED",
            url=page.url,
            reason="job_not_accepting_applications",
            diagnostic_actions=_visible_apply_actions(page),
        )

    trace_event(
        "application_entry_result",
        state="APPLICATION_ENTRY_NOT_FOUND",
        diagnostic_actions=list(_visible_apply_actions(page)),
    )
    return ApplicationEntryInspection(
        application_type="NO_APPLY_ENTRY_FOUND",
        application_state="APPLICATION_ENTRY_NOT_FOUND",
        url=page.url,
        reason="apply_button_not_detected_after_wait",
        diagnostic_actions=_visible_apply_actions(page),
    )
