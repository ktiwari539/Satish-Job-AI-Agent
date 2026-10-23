from dataclasses import dataclass, field
import re
from urllib.parse import urlsplit

from agent_trace import trace_event, trace_step
from browser_form_runtime import apply_fill_plan, build_page_fill_plan
from resume_evidence import inspect_resume_evidence
from live_blocker_capture import inspect_easy_apply_state


@dataclass(frozen=True)
class ApplicationFlowResult:
    state: str
    steps_completed: int = 0
    current_url: str = ""
    reasons: tuple[str, ...] = ()
    unknown_required_fields: tuple[str, ...] = ()
    missing_profile_values: tuple[str, ...] = ()
    actions: tuple[str, ...] = field(default_factory=tuple)
    review_checks: tuple[str, ...] = ()
    review_mismatches: tuple[str, ...] = ()
    visible_actions: tuple[str, ...] = ()


def _active_dialog_root(page) -> str:
    roots = (
        ".jobs-easy-apply-modal",
        # Real LinkedIn Easy Apply may render an artdeco-modal WITHOUT
        # role='dialog' (observed: progress 2/4 but modal_detected=false).
        ".artdeco-modal",
        "[role='dialog']",
    )
    for root in roots:
        try:
            locator = page.locator(root).first
            if locator.count() and locator.is_visible():
                return root
        except Exception:
            continue
    return ""


def _visible_action(page, texts: tuple[str, ...]):
    # Once Easy Apply is open, never fall back to a background-page button.
    # LinkedIn keeps other controls with the same text mounted behind the modal.
    root = _active_dialog_root(page)
    for text in texts:
        selectors = []
        if root:
            selectors.extend((
                f"{root} button:text-is('{text}')",
                f"{root} [role='button']:text-is('{text}')",
                f"{root} button[aria-label='{text}']",
                f"{root} [role='button'][aria-label='{text}']",
                f"{root} input[type='button'][value='{text}']",
                f"{root} input[type='submit'][value='{text}']",
                f"{root} button:has-text('{text}')",
                f"{root} [role='button']:has-text('{text}')",
                f"{root} button[aria-label*='{text}']",
                f"{root} [role='button'][aria-label*='{text}']",
            ))
        else:
            selectors.extend((
                f"button:text-is('{text}')",
                f"[role='button']:text-is('{text}')",
                f"button[aria-label='{text}']",
                f"[role='button'][aria-label='{text}']",
                f"input[type='button'][value='{text}']",
                f"input[type='submit'][value='{text}']",
                f"button:has-text('{text}')",
                f"[role='button']:has-text('{text}')",
                f"button[aria-label*='{text}']",
                f"[role='button'][aria-label*='{text}']",
                f"input[type='button'][value*='{text}']",
            ))
        for selector in selectors:
            try:
                matches = page.locator(selector)
                # LinkedIn can keep hidden/disabled copies of the same action.
                # .first alone may select a stale control while an enabled
                # "Next" remains visible later in the same modal.
                count = min(matches.count(), 20)
                for index in range(count):
                    target = matches.nth(index)
                    if target.is_visible() and target.is_enabled():
                        return target, text
            except (AttributeError, TypeError):
                # Support simple locator test doubles that expose only .first.
                try:
                    target = page.locator(selector).first
                    if target.count() and target.is_visible() and target.is_enabled():
                        return target, text
                except Exception:
                    continue
            except Exception:
                continue
    return None, ""




def _valid_contact_phone_step(page):
    """Read-only proof of one visible, filled, browser-valid phone field.

    This does not return or trace any personal value. It is only usable
    after the caller has independently verified Easy Apply opened.
    """
    script = r"""() => {
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 &&
          st.display !== 'none' && st.visibility !== 'hidden';
      };
      const fields = Array.from(document.querySelectorAll(
        'input[type="tel"], input[name*="phone" i], input[name*="mobile" i]'
      )).filter(visible);
      return fields.length === 1 &&
        String(fields[0].value || '').trim().length > 0 &&
        fields[0].checkValidity() &&
        fields[0].getAttribute('aria-invalid') !== 'true';
    }"""
    try:
        return page.evaluate(script) is True
    except Exception:
        return False


def _validated_required_wizard_fields(page, *, allow_optional_only=False) -> bool:
    """Validate all visible inputs, including optional-only wizard steps.

    Optional-only steps require prior verified progression (passed by the
    caller). This returns only a boolean: no values, labels or HTML leave the
    browser. Unknown required answers are independently blocked by FillPlan.
    """
    script = r"""(allowOptionalOnly) => {
      const visible = el => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 &&
          style.display !== 'none' && style.visibility !== 'hidden';
      };
      const fields = Array.from(document.querySelectorAll(
        'input, textarea, select'
      )).filter(el => visible(el) && !el.disabled);
      const required = fields.filter(el =>
        el.required || el.getAttribute('aria-required') === 'true');
      // An optional-only page is valid AFTER the preceding Easy Apply
      // pages have actually advanced. Do not require a mandatory field where
      // LinkedIn did not supply one.
      if (!fields.length || (!required.length && !allowOptionalOnly)) return false;
      return fields.every(el => {
        if (el.getAttribute('aria-invalid') === 'true') return false;
        if (typeof el.checkValidity === 'function' && !el.checkValidity())
          return false;
        if (!required.includes(el)) return true;
        if (['checkbox', 'radio'].includes((el.type || '').toLowerCase()))
          return !!el.checked;
        return String(el.value || '').trim().length > 0;
      });
    }"""
    try:
        return page.evaluate(script, bool(allow_optional_only)) is True
    except TypeError:
        # Test doubles and older page adapters may not accept evaluate args.
        # Avoid defaulting to trust on optional-only pages.
        if allow_optional_only:
            return False
        try:
            return page.evaluate(script) is True
        except Exception:
            return False
    except Exception:
        return False


def _progress_scoped_next(
    page, *, verified_contact_modal=False, confirmed_steps_completed=0
):
    """Find the intermediate Next control without guessing a modal selector.

    The normal CSS and accessible-name lookups stay first. This last-resort
    fallback is limited to non-final LinkedIn wizard steps with a
    verified Easy Apply entry and a validated form state (or the existing
    resume stage). We require exactly one enabled Next/Continue control;
    Submit/Apply controls are never eligible.
    """
    allowed = ("next", "next step", "continue", "continue to next step")
    try:
        host = (urlsplit(str(page.url)).hostname or "").lower()
        if host not in ("linkedin.com", "www.linkedin.com"):
            return None, ""
        progress = _easy_apply_progress(page)
        match = re.fullmatch(r"(\d+)/(\d+) pages", progress)
        if not match or not 1 <= int(match.group(1)) < int(match.group(2)):
            return None, ""

        root = _active_dialog_root(page)
        scope = page.locator(root).first if root else page
        try:
            controls = scope.get_by_role(
                "button", name=re.compile(r"^(?:Next|Next step|Continue|Continue to next step)$", re.I)
            )
            if 1 <= controls.count() <= 20:
                enabled = [
                    controls.nth(index)
                    for index in range(controls.count())
                    if controls.nth(index).is_visible() and controls.nth(index).is_enabled()
                ]
                if len(enabled) == 1:
                    target = enabled[0]
                    labels = []
                    for getter in (
                        lambda: target.inner_text(timeout=1000),
                        lambda: target.get_attribute("aria-label"),
                        lambda: target.get_attribute("value"),
                    ):
                        try:
                            labels.append(" ".join(str(getter() or "").split()))
                        except Exception:
                            continue
                    label = next((value for value in labels if value.casefold() in allowed), "")
                    if label:
                        trace_event("next_control_accessible_fallback", progress=progress, modal_scoped=bool(root))
                        return target, label
        except Exception:
            pass

        # The actual Oct 21 contact-step log reports progress 1/6,
        # a populated valid phone field, and exactly one visible enabled Next,
        # but fails to find a modal via the old selector. Unlike generic
        # page buttons, this is allowed ONLY after the caller has already
        # verified that Easy Apply opened as an application dialog.
        body_text = page.locator("body").inner_text(timeout=2000).casefold()
        resume_step = "upload resume" in body_text
        contact_step = bool(verified_contact_modal) and _valid_contact_phone_step(page)
        # The 3/6 screening step in the real log has a filled required
        # text control, no invalid fields, and exactly one enabled Next.
        # Preserve the initial confirmed Easy Apply entry as the trust gate
        # even when LinkedIn's modal wrapper is no longer detectable.
        confirmed_prior_progress = (
            bool(verified_contact_modal)
            and confirmed_steps_completed > 0
            and int(match.group(1)) == confirmed_steps_completed + 1
        )
        verified_wizard = (
            bool(verified_contact_modal)
            and _validated_required_wizard_fields(
                page, allow_optional_only=confirmed_prior_progress
            )
        )
        if not (resume_step or contact_step or verified_wizard):
            trace_event("next_fallback_not_verified", progress=progress,
                        resume_step=resume_step, verified_entry=bool(verified_contact_modal),
                        contact_step=contact_step, verified_wizard=verified_wizard,
                        confirmed_prior_progress=confirmed_prior_progress)
            return None, ""
        controls = page.locator(
            'button, [role="button"], input[type="button"], input[type="submit"]'
        )
        count = controls.count()
        if not 1 <= count <= 400:
            return None, ""

        enabled = []
        for index in range(count):
            target = controls.nth(index)
            if not target.is_visible() or not target.is_enabled():
                continue
            labels = []
            for getter in (
                lambda: target.inner_text(timeout=500),
                lambda: target.get_attribute("aria-label"),
                lambda: target.get_attribute("value"),
            ):
                try:
                    labels.append(" ".join(str(getter() or "").split()).casefold())
                except Exception:
                    pass
            if any(value in allowed for value in labels):
                enabled.append((target, next(value for value in labels if value in allowed)))

        if len(enabled) != 1:
            return None, ""
        target, label = enabled[0]
        trace_event("next_control_dom_fallback", progress=progress, modal_scoped=bool(root),
                    context="resume" if resume_step else (
                        "verified_contact" if contact_step else "verified_wizard"))
        return target, label
    except Exception:
        return None, ""


def _canonical_progress(text: str) -> str:
    """Extract LinkedIn's visible page counter into a stable canonical form."""
    match = re.search(r"(?<!\d)(\d+)\s*/\s*(\d+)\s*pages?\b", str(text), re.I)
    if not match:
        return ""
    return f"{int(match.group(1))}/{int(match.group(2))} pages"


def _easy_apply_progress(page) -> str:
    """Return a stable LinkedIn Easy Apply progress marker such as '1/4 pages'.

    LinkedIn's modal wrapper varies between deployments. Prefer the active modal,
    but fall back to the visible page text so a displayed counter never becomes
    'unknown' just because a wrapper class/role changed.
    """
    script = r"""
    () => {
      const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          rect.width > 0 && rect.height > 0;
      };

      const roots = Array.from(document.querySelectorAll(
        '.jobs-easy-apply-modal, .artdeco-modal, [role="dialog"]'
      )).filter(visible);

      for (const root of roots) {
        const text = clean(root.innerText || root.textContent);
        const match = text.match(/\b\d+\s*\/\s*\d+\s*pages?\b/i);
        if (match) return match[0];
      }

      const bodyText = clean(document.body && document.body.innerText);
      const bodyMatch = bodyText.match(/\b\d+\s*\/\s*\d+\s*pages?\b/i);
      return bodyMatch ? bodyMatch[0] : '';
    }
    """
    try:
        progress = _canonical_progress(str(page.evaluate(script) or ""))
        if progress:
            return progress
    except Exception:
        pass

    try:
        return _canonical_progress(page.locator("body").inner_text(timeout=2000))
    except Exception:
        return ""


def _application_step_signature(page) -> str:
    """Fallback stable signature for the visible Easy Apply step.

    LinkedIn-generated ids/names are deliberately excluded because they can
    change during a re-render without the user actually moving to another step.
    """
    script = r"""
    () => {
      const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          rect.width > 0 && rect.height > 0;
      };

      const roots = Array.from(document.querySelectorAll(
        '.jobs-easy-apply-modal, .artdeco-modal[role="dialog"], [role="dialog"]'
      )).filter(visible);

      const root = roots.find((candidate) => {
        const text = clean(candidate.innerText || candidate.textContent);
        return /\b\d+\s*\/\s*\d+\s*pages?\b/i.test(text) ||
          /apply to /i.test(text);
      });
      if (!root) return '';

      const labels = [];
      const seen = new Set();
      const add = (value) => {
        const text = clean(value);
        if (!text || seen.has(text)) return;
        seen.add(text);
        labels.push(text);
      };

      Array.from(root.querySelectorAll(
        'h1, h2, h3, legend, label, .fb-dash-form-element__label'
      )).filter(visible).forEach((el) => add(el.innerText || el.textContent));

      Array.from(root.querySelectorAll('input, textarea, select'))
        .filter((el) => !el.disabled && (el.type || '').toLowerCase() !== 'hidden')
        .forEach((el) => {
          const labelledBy = (el.getAttribute('aria-labelledby') || '').trim();
          if (labelledBy) {
            labelledBy.split(/\s+/).forEach((token) => {
              const node = document.getElementById(token);
              if (node) add(node.innerText || node.textContent);
            });
          }
          add(el.getAttribute('aria-label'));
          add(el.getAttribute('placeholder'));
        });

      return labels.slice(0, 30).join('|');
    }
    """
    try:
        return str(page.evaluate(script) or "")
    except Exception:
        return ""


def _blocking_confirmation_dialog(page) -> str:
    """Return text for a visible confirmation dialog that blocks Easy Apply."""
    script = r"""
    () => {
      const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          rect.width > 0 && rect.height > 0;
      };
      const dialogs = Array.from(document.querySelectorAll('[role="dialog"], .artdeco-modal'))
        .filter(visible);
      for (const dialog of dialogs) {
        const text = clean(dialog.innerText || dialog.textContent);
        if (/save this application\?/i.test(text) ||
            /save to return to this application later/i.test(text)) {
          return text;
        }
      }
      return '';
    }
    """
    try:
        return str(page.evaluate(script) or "")
    except Exception:
        return ""


def _wait_for_step_transition(
    page,
    before_progress: str,
    before_signature: str,
    timeout_ms: int = 3500,
) -> bool:
    elapsed = 0
    interval = 250

    while elapsed < timeout_ms:
        page.wait_for_timeout(interval)
        elapsed += interval

        # A confirmation overlay is not application progress.
        if _blocking_confirmation_dialog(page):
            return False

        after_progress = _easy_apply_progress(page)
        if before_progress:
            # When LinkedIn exposes "1/4 pages", that counter is authoritative.
            if after_progress and after_progress != before_progress:
                return True
            continue

        after_signature = _application_step_signature(page)
        if before_signature and after_signature and after_signature != before_signature:
            return True

    return False


def _navigation_target_identity(target) -> str:
    """Return stable text/attributes used to reject destructive modal controls."""
    values = []
    for getter in (
        lambda: target.inner_text(timeout=1000),
        lambda: target.get_attribute("aria-label"),
        # An input[type=button] or input[type=submit] uses its value rather
        # than inner_text for the visible action name.
        lambda: target.get_attribute("value"),
        lambda: target.get_attribute("title"),
        lambda: target.get_attribute("data-control-name"),
    ):
        try:
            value = getter()
        except Exception:
            value = ""
        value = " ".join(str(value or "").split()).strip()
        if value:
            values.append(value)
    return " | ".join(dict.fromkeys(values))


def _click_action(target, expected_action: str = "") -> None:
    """Click only the resolved visible navigation control.

    Do not use force=True or DOM el.click() here. LinkedIn re-renders Easy Apply
    controls aggressively; those fallbacks can act on a stale/replaced element
    and are unsafe for modal navigation.
    """
    identity = _navigation_target_identity(target)
    lowered = identity.lower()
    blocked_tokens = ("dismiss", "close", "discard", "save this application", "save application")
    if any(token in lowered for token in blocked_tokens):
        raise RuntimeError(f"unsafe_navigation_target:{identity or 'unknown'}")

    # A Next/Continue target cannot also advertise submission through ARIA
    # or another attribute. Avoid accidentally submitting the job when the
    # visible label and accessible action disagree.
    if expected_action.casefold() in ("next", "next step", "continue", "continue to next step"):
        if re.search(r"\b(?:submit|send application|complete application|apply now)\b", lowered):
            raise RuntimeError("unsafe_next_target_advertises_submission")

    if expected_action and identity:
        expected = expected_action.lower()
        if expected not in lowered:
            raise RuntimeError(
                f"navigation_target_mismatch:expected={expected_action}:actual={identity}"
            )

    try:
        target.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass

    target.click(timeout=5000)




def _visible_action_texts(page) -> tuple[str, ...]:
    script = """
    () => Array.from(document.querySelectorAll(
      '.jobs-easy-apply-modal button, .jobs-easy-apply-modal [role="button"], button, [role="button"]'
    ))
      .filter((el) => {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return !el.disabled && style.visibility !== 'hidden' &&
          style.display !== 'none' && rect.width > 0 && rect.height > 0;
      })
      .map((el) => (
        el.innerText || el.textContent || el.getAttribute('aria-label') || ''
      ).replace(/\\s+/g, ' ').trim())
      .filter(Boolean)
      .slice(0, 20)
    """
    try:
        values = page.evaluate(script) or []
    except Exception:
        values = []
    # Buttons on LinkedIn's resume page can contain uploaded document names,
    # dates, and other identifying details. Keep only fixed navigation labels.
    diagnostic_actions = {
        "next", "next step", "continue", "continue to next step",
        "back", "previous", "review", "review application",
        "review your application", "submit", "submit application",
        "send application", "upload resume", "dismiss", "close", "cancel",
    }
    return tuple(dict.fromkeys(
        str(v).strip()
        for v in values
        if str(v).strip().casefold() in diagnostic_actions
    ))



def _next_action_diagnostics(page) -> dict:
    """Read-only, non-personal diagnostics for a visible but unresolved Next.

    Distinguish a disabled resume-stage button from a selector/scoping mismatch.
    Never return field values, labels, resume names or page text.
    """
    script = r"""
    () => {
      const roots = Array.from(document.querySelectorAll(
        '.jobs-easy-apply-modal, .artdeco-modal, [role="dialog"]'
      ));
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 &&
          style.display !== 'none' && style.visibility !== 'hidden';
      };
      const root = roots.find(visible);
      const buttons = Array.from(document.querySelectorAll(
        'button, [role="button"], input[type="button"]'
      ));
      const next = buttons.filter((el) => {
        const text = (el.innerText || el.textContent ||
          el.getAttribute('aria-label') || el.value || '')
          .replace(/\\s+/g, ' ').trim().toLowerCase();
        return ['next', 'next step', 'continue', 'continue to next step']
          .includes(text);
      });
      // Structural metadata only. Never record the control's text, value,
      // attributes with user content, parent HTML, or full DOM.
      const candidate = next.filter(visible)[0] || null;
      const tag = candidate ? candidate.tagName.toLowerCase() : '';
      const type = candidate ? (candidate.getAttribute('type') || '').toLowerCase() : '';
      const role = candidate ? (candidate.getAttribute('role') || '').toLowerCase() : '';
      return {
        modal_detected: !!root,
        next_control_tag: ['button', 'input', 'a', 'div', 'span'].includes(tag) ? tag : 'other',
        next_control_type: ['button', 'submit', 'reset', ''].includes(type) ? type : 'other',
        next_control_role: ['button', ''].includes(role) ? role : 'other',
        next_inside_form: !!(candidate && candidate.closest('form')),
        next_candidates: Math.min(next.length, 100),
        next_visible: next.filter(visible).length,
        next_visible_enabled: next.filter((el) =>
          visible(el) && !el.disabled &&
          el.getAttribute('aria-disabled') !== 'true'
        ).length,
        next_inside_active_modal: root ?
          next.filter((el) => root.contains(el)).length : 0,
        next_inside_modal_enabled: root ?
          next.filter((el) => root.contains(el) && visible(el) &&
            !el.disabled && el.getAttribute('aria-disabled') !== 'true'
          ).length : 0,
      };
    }
    """
    try:
        result = page.evaluate(script)
        return result if isinstance(result, dict) else {"diagnostic": "unavailable"}
    except Exception:
        return {"diagnostic": "unavailable"}


def _normalize_digits(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def _inspect_review(page, profile: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    try:
        body = page.locator("body").inner_text(timeout=5000)
    except Exception:
        body = ""
    normalized_body = " ".join(body.lower().split())
    body_digits = _normalize_digits(body)

    checks: list[str] = []
    mismatches: list[str] = []

    # Review pages often omit profile URLs even when they were supplied on an
    # earlier step. Validate stable identity fields that should be rendered.
    for key in ("email", "phone", "full_name"):
        raw = profile.get(key)
        if raw in (None, ""):
            continue
        value = str(raw).strip()
        if key == "phone":
            digits = _normalize_digits(value)
            matched = bool(digits) and digits in body_digits
        else:
            matched = value.lower() in normalized_body
        checks.append(f"{key}:{'matched' if matched else 'missing'}")
        if not matched:
            mismatches.append(key)

    return tuple(checks), tuple(mismatches)


_REQUIRED_SCREENING_PROBE = r"""() => {
  // Only structural state is returned. Never return labels, text answers,
  // selected options, applicant values, HTML or page URLs.
  const visible = el => {
    if (!el || !el.isConnected) return false;
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== 'none' && style.visibility !== 'hidden';
  };
  const activeChoice = el => {
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
    if (visible(el)) return true;
    // Styled LinkedIn radio buttons often hide the native input while
    // showing its connected label; a hidden native input is still a choice.
    if (el.matches('input[type="radio"],input[type="checkbox"]')) {
      if (Array.from(el.labels || []).some(visible)) return true;
      const wrapper = el.closest('label');
      if (wrapper && visible(wrapper)) return true;
    }
    return false;
  };
  const containers = new Set();
  for (const input of document.querySelectorAll(
    'input[type="radio"],[role="radio"],input[type="checkbox"]'
  )) {
    if (!activeChoice(input)) continue;
    const group = input.closest(
      '[role="radiogroup"],fieldset,' +
      '[data-test-form-builder-radio-button-form-component],' +
      '[class*="radio-button-form-component"],.fb-dash-form-element'
    );
    if (group && visible(group)) containers.add(group);
  }
  let requiredRadioGroups = 0, missingRadioGroups = 0;
  let requiredCheckboxGroups = 0, missingCheckboxGroups = 0;
  let unknownRequiredGroups = 0;
  for (const root of containers) {
    const radios = Array.from(root.querySelectorAll(
      'input[type="radio"],[role="radio"]'
    )).filter(activeChoice);
    const checkboxes = Array.from(root.querySelectorAll(
      'input[type="checkbox"]'
    )).filter(activeChoice);
    const legend = root.querySelector(
      'legend,.fb-dash-form-element__label,[class*="form-element__label"]'
    );
    const questionText = String(legend?.innerText || legend?.textContent || '');
    const requiredMarker = Boolean(root.querySelector(
      '[aria-required="true"],[data-required="true"],' +
      '[class*="required-indicator"],[class*="required-marker"]'
    ));
    const isRequired = root.getAttribute('aria-required') === 'true' ||
      root.getAttribute('data-required') === 'true' ||
      /(^|\s)required(\s|$)/i.test(root.className || '') ||
      Boolean(legend && /[*]|[(]required[)]/i.test(questionText)) ||
      requiredMarker ||
      [...radios, ...checkboxes].some(el =>
        el.required || el.getAttribute('aria-required') === 'true');
    if (!isRequired) continue;
    if (radios.length > 0) {
      requiredRadioGroups++;
      if (!radios.some(el => el.checked ||
          el.getAttribute('aria-checked') === 'true')) missingRadioGroups++;
    } else if (checkboxes.length > 0) {
      // Only a positively marked required checkbox group is checked.
      requiredCheckboxGroups++;
      if (!checkboxes.some(el => el.checked)) missingCheckboxGroups++;
    } else unknownRequiredGroups++;
  }
  // LinkedIn may omit native required attributes and wrap each question in
  // custom React containers. Check visible radio names independently of
  // required markers; never assume an unanswered group is optional.
  const groupNames = new Map();
  const allRadios = Array.from(document.querySelectorAll(
    'input[type="radio"],[role="radio"]'
  )).filter(activeChoice);
  for (const radio of allRadios) {
    const container = radio.closest(
      '[role="radiogroup"],fieldset,[class*="radio-button-form-component"],' +
      '.fb-dash-form-element'
    );
    const name = (radio.getAttribute('name') || '').trim();
    const key = container || (name ? 'name:' + name : radio);
    if (!groupNames.has(key)) groupNames.set(key, []);
    groupNames.get(key).push(radio);
  }
  let unansweredRadioGroups = 0;
  for (const group of groupNames.values()) {
    if (!group.some(el => el.checked ||
        el.getAttribute('aria-checked') === 'true')) unansweredRadioGroups++;
  }
  return {
    required_radio_groups: requiredRadioGroups,
    missing_radio_groups: missingRadioGroups,
    required_checkbox_groups: requiredCheckboxGroups,
    missing_checkbox_groups: missingCheckboxGroups,
    unknown_required_groups: unknownRequiredGroups,
    visible_radio_groups: groupNames.size,
    unanswered_radio_groups: unansweredRadioGroups,
    custom_styled_radio_options: allRadios.filter(el =>
      !visible(el) && activeChoice(el)).length
  };
}"""


def _required_screening_probe(page) -> dict:
    """Return zero-or-positive structural counts; never surface user answers."""
    keys = (
        "required_radio_groups", "missing_radio_groups",
        "required_checkbox_groups", "missing_checkbox_groups",
        "unknown_required_groups",
        "visible_radio_groups", "unanswered_radio_groups",
        "custom_styled_radio_options",
    )
    try:
        raw = page.evaluate(_REQUIRED_SCREENING_PROBE)
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        key: min(max(raw.get(key, 0), 0), 100)
        if type(raw.get(key)) is int else 0
        for key in keys
    }


def run_safe_application_flow(
    page,
    profile: dict,
    *,
    resume_path: str = "",
    advance: bool = False,
    inspect_review: bool = False,
    max_steps: int = 6,
    live_submission_enabled: bool = False,
    application_type: str = "LINKEDIN_EASY_APPLY",
    verified_easy_apply_modal: bool = False,
) -> ApplicationFlowResult:
    actions: list[str] = []
    steps_completed = 0
    resume_verified = False
    resume_mismatch_seen = False
    latest_resume_state = "attachment_unverified"

    def require_resume_evidence():
        if not (live_submission_enabled and resume_path):
            return ()
        if resume_mismatch_seen:
            return ("different_resume_selected",)
        if not resume_verified:
            return ("resume_attachment_unverified",)
        return ()

    trace_event(
        "application_flow_start",
        advance=advance,
        inspect_review=inspect_review,
        max_steps=max_steps,
        current_url=str(getattr(page, "url", "") or ""),
    )

    for step_index in range(max_steps):
        trace_event(
            "application_form_step_start",
            step_index=step_index,
            steps_completed=steps_completed,
            current_url=str(getattr(page, "url", "") or ""),
        )
        inspect_easy_apply_state(page, stage="before_fill", step_index=step_index)
        confirmation = _blocking_confirmation_dialog(page)
        if confirmation:
            return ApplicationFlowResult(
                state="BLOCKED_CONFIRMATION_DIALOG",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=("unexpected_save_application_dialog",),
                actions=tuple(actions),
                visible_actions=_visible_action_texts(page),
            )

        with trace_step("form_plan_build", step_index=step_index):
            plan = build_page_fill_plan(
                page,
                profile,
                resume_path=resume_path,
                live_submission_enabled=live_submission_enabled,
            )
        trace_event(
            "form_plan_result",
            step_index=step_index,
            known_field_count=len(plan.values),
            unknown_required_fields=list(plan.unknown_required_fields),
            missing_profile_values=list(plan.missing_profile_values),
            can_fill=plan.can_fill,
            resume_upload_planned=bool(plan.resume_path),
            resume_path_configured=bool(resume_path),
            reasons=list(plan.reasons),
        )

        if plan.unknown_required_fields:
            return ApplicationFlowResult(
                state="BLOCKED_UNKNOWN_REQUIRED_FIELDS",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=plan.reasons,
                unknown_required_fields=plan.unknown_required_fields,
                missing_profile_values=plan.missing_profile_values,
                actions=tuple(actions),
            )

        if plan.missing_profile_values or not plan.can_fill:
            return ApplicationFlowResult(
                state="BLOCKED_INCOMPLETE_OR_AUTH",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=plan.reasons,
                unknown_required_fields=plan.unknown_required_fields,
                missing_profile_values=plan.missing_profile_values,
                actions=tuple(actions),
            )

        with trace_step("form_fill", step_index=step_index, known_field_count=len(plan.values)):
            fill_reasons = apply_fill_plan(
                page, plan, verify_readback=(advance or live_submission_enabled)
            )
        trace_event(
            "form_fill_result",
            step_index=step_index,
            reasons=list(fill_reasons),
            resume_upload_planned=bool(plan.resume_path),
            resume_path_configured=bool(resume_path),
        )
        if resume_path:
            latest_resume_state = inspect_resume_evidence(page, resume_path)
            if latest_resume_state == "matching_resume_selected":
                resume_verified = True
                resume_mismatch_seen = False
            if latest_resume_state == "different_resume_selected":
                resume_mismatch_seen = True
                resume_verified = False
            trace_event(
                "resume_attachment_inspection", step_index=step_index,
                state=latest_resume_state,
                matching_selection_seen=resume_verified,
                mismatch_seen=resume_mismatch_seen,
            )
        inspect_easy_apply_state(page, stage="after_fill", step_index=step_index)
        actions.append(f"planned_known_fields:{len(plan.values)}")
        if plan.resume_path and not any(
            reason in {"resume_upload_failed", "resume_upload_input_not_found"}
            for reason in fill_reasons
        ):
            actions.append("resume_file_input_set")

        if any(
            reason in {
                "captcha_requires_human",
                "manual_auth_required",
                "answers_incomplete_or_unverified",
                "resume_upload_failed",
                "resume_upload_input_not_found",
                "form_readback_unavailable",
                "form_readback_invalid",
            }
            or reason.startswith("field_value_unverified:")
            or reason.startswith("field_not_found:")
            or reason.startswith("field_fill_failed:")
            or reason.startswith("radio_not_selected:")
            or reason.startswith("radio_option_not_found:")
            for reason in fill_reasons
        ):
            return ApplicationFlowResult(
                state="BLOCKED_AFTER_FILL",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=fill_reasons,
                actions=tuple(actions),
            )

        review, review_text = _visible_action(
            page,
            ("Review", "Review application", "Review your application"),
        )
        if review is not None:
            trace_event(
                "review_control_detected",
                step_index=step_index,
                control_text=review_text,
                inspect_review=inspect_review,
            )
            if not inspect_review:
                actions.append(f"stopped_before:{review_text}")
                return ApplicationFlowResult(
                    state="REVIEW_READY",
                    steps_completed=steps_completed,
                    current_url=page.url,
                    reasons=plan.reasons,
                    actions=tuple(actions),
                )

            choice_probe = _required_screening_probe(page)
            trace_event(
                "review_required_choice_preflight",
                step_index=step_index, **choice_probe,
            )
            if (
                choice_probe["missing_radio_groups"]
                or choice_probe["missing_checkbox_groups"]
            ):
                actions.append("review_not_clicked_missing_required_choices")
                return ApplicationFlowResult(
                    state="BLOCKED_REQUIRED_SCREENING_ANSWERS",
                    steps_completed=steps_completed,
                    current_url=page.url,
                    reasons=("unanswered_required_choice_group",),
                    actions=tuple(actions),
                )
            if choice_probe.get("unanswered_radio_groups", 0):
                # A custom question may be mandatory despite having no
                # browser-required marker. It is never safe to infer an answer
                # or silently proceed to a blocked Review screen.
                trace_event(
                    "review_unanswered_radio_groups",
                    count=choice_probe.get("unanswered_radio_groups", 0),
                    question_text_logged=False,
                )
                actions.append("review_not_clicked_unverified_radio_choices")
                return ApplicationFlowResult(
                    state="BLOCKED_UNVERIFIED_SCREENING_CHOICES",
                    steps_completed=steps_completed,
                    current_url=page.url,
                    reasons=("unanswered_radio_groups_without_required_markup",),
                    actions=tuple(actions),
                )

            try:
                with trace_step("review_open", step_index=step_index, control_text=review_text):
                    _click_action(review, review_text)
                    page.wait_for_timeout(800)
                actions.append(f"clicked:{review_text}")
            except Exception as exc:
                return ApplicationFlowResult(
                    state="REVIEW_OPEN_FAILED",
                    steps_completed=steps_completed,
                    current_url=page.url,
                    reasons=(f"review_click_failed:{type(exc).__name__}",),
                    actions=tuple(actions),
                )

            review_submit_texts = (
                ("Submit application", "Submit", "Send application")
                if application_type == "LINKEDIN_EASY_APPLY"
                else (
                    "Submit application",
                    "Submit Application",
                    "Submit",
                    "Send application",
                    "Send Application",
                    "Complete application",
                    "Complete Application",
                    "Apply",
                    "Apply Now",
                )
            )
            submit, submit_text = _visible_action(page, review_submit_texts)
            try:
                body_after_review = page.locator("body").inner_text(timeout=3000).lower()
            except Exception:
                body_after_review = ""

            if submit is None and "this field is required" in body_after_review:
                validation_probe = _required_screening_probe(page)
                trace_event(
                    "review_validation_blocker_details",
                    step_index=step_index,
                    **validation_probe,
                    review_remained_visible=True,
                    submit_visible=False,
                    known_required_warning=True,
                )
                actions.append("review_validation_blocked")
                return ApplicationFlowResult(
                    state="REVIEW_VALIDATION_BLOCKED",
                    steps_completed=steps_completed,
                    current_url=page.url,
                    reasons=tuple(dict.fromkeys((
                        *plan.reasons,
                        "review_validation_required_warning",
                        *(
                            ("unanswered_required_choice_group",)
                            if (validation_probe["missing_radio_groups"] or
                                validation_probe["missing_checkbox_groups"])
                            else ()
                        ),
                    ))),
                    actions=tuple(actions),
                    visible_actions=_visible_action_texts(page),
                )

            with trace_step("review_validation", step_index=step_index):
                review_checks, review_mismatches = _inspect_review(page, profile)
            trace_event(
                "review_validation_result",
                step_index=step_index,
                checks=list(review_checks),
                mismatches=list(review_mismatches),
                submit_control_found=submit is not None,
            )
            if submit is not None:
                actions.append(f"stopped_before:{submit_text}")
            else:
                actions.append("review_opened_no_submit_clicked")

            # The Review page may expose selected resume evidence when the
            # earlier resume step did not. Read only, never log filenames.
            if resume_path:
                latest_resume_state = inspect_resume_evidence(page, resume_path)
                if latest_resume_state == "matching_resume_selected":
                    resume_verified = True
                    resume_mismatch_seen = False
                if latest_resume_state == "different_resume_selected":
                    resume_mismatch_seen = True
                    resume_verified = False
                trace_event(
                    "resume_attachment_review_inspection",
                    state=latest_resume_state,
                    matching_selection_seen=resume_verified,
                    mismatch_seen=resume_mismatch_seen,
                )
            resume_reasons = require_resume_evidence()
            if resume_reasons:
                return ApplicationFlowResult(
                    state="BLOCKED_RESUME_UNVERIFIED",
                    steps_completed=steps_completed,
                    current_url=page.url,
                    reasons=resume_reasons,
                    actions=tuple(actions),
                    review_checks=review_checks,
                    review_mismatches=review_mismatches,
                )

            next_state = "REVIEW_MISMATCH" if review_mismatches else "REVIEW_INSPECTED"
            if (
                not review_mismatches
                and submit is not None
                and live_submission_enabled
            ):
                next_state = "SUBMIT_READY"

            return ApplicationFlowResult(
                state=next_state,
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=plan.reasons,
                actions=tuple(actions),
                review_checks=review_checks,
                review_mismatches=review_mismatches,
            )

        submit_texts = (
            ("Submit application", "Submit", "Send application")
            if application_type == "LINKEDIN_EASY_APPLY"
            else (
                "Submit application",
                "Submit Application",
                "Submit",
                "Send application",
                "Send Application",
                "Complete application",
                "Complete Application",
                "Apply",
                "Apply Now",
            )
        )
        submit, submit_text = _visible_action(page, submit_texts)
        if submit is not None:
            resume_reasons = require_resume_evidence()
            if resume_reasons:
                trace_event(
                    "resume_attachment_submit_blocked",
                    reason=resume_reasons[0],
                    last_state=latest_resume_state,
                )
                return ApplicationFlowResult(
                    state="BLOCKED_RESUME_UNVERIFIED",
                    steps_completed=steps_completed,
                    current_url=page.url,
                    reasons=resume_reasons,
                    actions=tuple(actions),
                )
            trace_event(
                "submit_control_detected",
                step_index=step_index,
                control_text=submit_text,
            )
            actions.append(f"stopped_before:{submit_text}")
            return ApplicationFlowResult(
                state="SUBMIT_READY",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=plan.reasons,
                actions=tuple(actions),
            )

        if not advance:
            return ApplicationFlowResult(
                state="FILLED_CURRENT_STEP",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=plan.reasons,
                actions=tuple(actions),
            )

        next_button, next_text = _visible_action(
            page,
            ("Next", "Next step", "Continue", "Continue to next step"),
        )
        if next_button is None and application_type == "LINKEDIN_EASY_APPLY":
            next_button, next_text = _progress_scoped_next(
                page,
                verified_contact_modal=verified_easy_apply_modal,
                confirmed_steps_completed=steps_completed,
            )
        if next_button is None:
            diagnostic = _next_action_diagnostics(page)
            if diagnostic.get("next_visible", 0) and not diagnostic.get("next_visible_enabled", 0):
                failure_reason = "next_control_disabled"
            elif diagnostic.get("modal_detected") and diagnostic.get("next_visible_enabled", 0) and not diagnostic.get("next_inside_modal_enabled", 0):
                failure_reason = "next_control_outside_active_modal"
            elif diagnostic.get("next_inside_modal_enabled", 0):
                failure_reason = "next_selector_mismatch"
            else:
                failure_reason = "safe_next_control_not_found"
            trace_event(
                "next_control_not_found",
                step_index=step_index,
                failure_reason=failure_reason,
                next_diagnostic=diagnostic,
                visible_actions=list(_visible_action_texts(page)),
            )
            return ApplicationFlowResult(
                state="NO_SAFE_NEXT_ACTION",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=tuple(dict.fromkeys((*plan.reasons, failure_reason))),
                actions=tuple(actions),
                visible_actions=_visible_action_texts(page),
            )

        before_progress = _easy_apply_progress(page)
        before_signature = _application_step_signature(page)
        trace_event(
            "next_control_detected",
            step_index=step_index,
            control_text=next_text,
            before_progress=before_progress,
            before_signature_present=bool(before_signature),
        )
        try:
            with trace_step(
                "next_transition",
                step_index=step_index,
                control_text=next_text,
                before_progress=before_progress,
            ):
                _click_action(next_button, next_text)
                transitioned = _wait_for_step_transition(
                    page,
                    before_progress,
                    before_signature,
                )
            if not transitioned:
                confirmation = _blocking_confirmation_dialog(page)
                if confirmation:
                    return ApplicationFlowResult(
                        state="BLOCKED_CONFIRMATION_DIALOG",
                        steps_completed=steps_completed,
                        current_url=page.url,
                        reasons=("unexpected_save_application_dialog",),
                        actions=tuple(actions + [f"clicked:{next_text}"]),
                        visible_actions=_visible_action_texts(page),
                    )
                return ApplicationFlowResult(
                    state="NEXT_NO_TRANSITION",
                    steps_completed=steps_completed,
                    current_url=page.url,
                    reasons=(
                        f"easy_apply_progress_unchanged:{before_progress or 'unknown'}",
                    ),
                    actions=tuple(actions + [f"clicked_no_transition:{next_text}"]),
                    visible_actions=_visible_action_texts(page),
                )
            steps_completed += 1
            actions.append(f"clicked:{next_text}")
            trace_event(
                "next_transition_confirmed",
                step_index=step_index,
                control_text=next_text,
                steps_completed=steps_completed,
                after_progress=_easy_apply_progress(page),
            )
        except Exception as exc:
            return ApplicationFlowResult(
                state="NEXT_ACTION_FAILED",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=(f"next_click_failed:{type(exc).__name__}",),
                actions=tuple(actions),
            )

    trace_event(
        "application_flow_max_steps_reached",
        steps_completed=steps_completed,
        max_steps=max_steps,
    )
    return ApplicationFlowResult(
        state="MAX_SAFE_STEPS_REACHED",
        steps_completed=steps_completed,
        current_url=page.url,
        actions=tuple(actions),
    )
