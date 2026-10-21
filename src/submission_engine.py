from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class SubmissionResult:
    state: str
    confirmed: bool = False
    reason: str = ""
    evidence: str = ""
    current_url: str = ""
    actions: Tuple[str, ...] = field(default_factory=tuple)


def _active_dialog_root(page) -> str:
    for selector in (
        ".jobs-easy-apply-modal",
        ".artdeco-modal",
        "[role='dialog']",
    ):
        try:
            target = page.locator(selector).first
            if target.count() and target.is_visible():
                return selector
        except Exception:
            continue
    return ""


def _visible_submit_control(page, application_type: str = "LINKEDIN_EASY_APPLY"):
    root = _active_dialog_root(page)
    texts = (
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
    for text in texts:
        selectors = []
        if root:
            selectors.extend(
                (
                    f"{root} button:text-is('{text}')",
                    f"{root} [role='button']:text-is('{text}')",
                    f"{root} button[aria-label='{text}']",
                    f"{root} [role='button'][aria-label='{text}']",
                )
            )
        else:
            selectors.extend(
                (
                    f"button:text-is('{text}')",
                    f"[role='button']:text-is('{text}')",
                    f"button[aria-label='{text}']",
                    f"[role='button'][aria-label='{text}']",
                )
            )
        for selector in selectors:
            try:
                target = page.locator(selector).first
                if target.count() and target.is_visible() and target.is_enabled():
                    return target, text
            except Exception:
                continue
    return None, ""


def _control_identity(target) -> str:
    values = []
    for getter in (
        lambda: target.inner_text(timeout=1000),
        lambda: target.get_attribute("aria-label"),
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


def detect_linkedin_submission_confirmation(page) -> str:
    """Return positive confirmation evidence or an empty string.

    Evidence is limited to visible post-submit UI such as the confirmation
    dialog or a visible Applied control. Background page text alone is not
    sufficient because LinkedIn can contain historical application text.
    """
    script = r"""
    () => {
      const clean = (v) => (v || '').replace(/s+/g, ' ').trim();
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' &&
          style.visibility !== 'hidden' &&
          rect.width > 0 &&
          rect.height > 0;
      };

      const confirmationMarkers = [
        /application submitted/i,
        /your application was sent/i,
        /application was sent/i,
        /application sent/i,
        /successfully applied/i
      ];

      const roots = Array.from(document.querySelectorAll(
        '.jobs-easy-apply-modal, .artdeco-modal, [role="dialog"]'
      )).filter(visible);

      for (const root of roots) {
        const text = clean(root.innerText || root.textContent);
        if (confirmationMarkers.some((pattern) => pattern.test(text))) {
          return 'confirmation_dialog:' + text.slice(0, 240);
        }
      }

      const appliedControls = Array.from(document.querySelectorAll(
        'button, [role="button"], .jobs-apply-button'
      )).filter(visible);
      for (const control of appliedControls) {
        const text = clean(
          control.innerText ||
          control.textContent ||
          control.getAttribute('aria-label')
        );
        if (/^applied$/i.test(text) || /^application submitted$/i.test(text)) {
          return 'applied_control:' + text;
        }
      }
      return '';
    }
    """
    try:
        return str(page.evaluate(script) or "").strip()
    except Exception:
        return ""


def _wait_for_linkedin_confirmation(page, timeout_ms: int = 8000) -> str:
    elapsed = 0
    interval = 250
    while elapsed <= timeout_ms:
        evidence = detect_linkedin_submission_confirmation(page)
        if evidence:
            return evidence
        if elapsed >= timeout_ms:
            break
        try:
            page.wait_for_timeout(interval)
        except Exception:
            break
        elapsed += interval
    return ""


def _visible_body_text(page) -> str:
    try:
        return " ".join(page.locator("body").inner_text(timeout=3000).split())
    except Exception:
        return ""


def detect_external_submission_confirmation(page, *, before_url: str = "") -> str:
    """Detect strong post-submit evidence on external ATS pages."""
    current_url = str(getattr(page, "url", "") or "")
    body = _visible_body_text(page)
    lowered = body.lower()

    markers = (
        "thank you for applying",
        "thank you for your application",
        "application submitted",
        "application successfully submitted",
        "your application has been submitted",
        "application received",
        "your application has been received",
        "we have received your application",
        "we've received your application",
        "successfully applied",
    )
    matched = next((marker for marker in markers if marker in lowered), "")
    if not matched:
        return ""

    submit, _ = _visible_submit_control(page, "EXTERNAL_APPLY")
    submit_still_visible = submit is not None
    url_changed = bool(before_url and current_url and current_url != before_url)
    confirmation_url = any(
        token in current_url.lower()
        for token in ("thank", "success", "confirm", "submitted", "application-complete")
    )

    if url_changed or confirmation_url or not submit_still_visible:
        return f"external_confirmation:{matched}"
    return ""


def _wait_for_external_confirmation(page, *, before_url: str, timeout_ms: int = 10000) -> str:
    elapsed = 0
    interval = 250
    while elapsed <= timeout_ms:
        evidence = detect_external_submission_confirmation(page, before_url=before_url)
        if evidence:
            return evidence
        if elapsed >= timeout_ms:
            break
        try:
            page.wait_for_timeout(interval)
        except Exception:
            break
        elapsed += interval
    return ""


def submit_application(
    page,
    *,
    application_type: str,
    live_submission_enabled: bool,
    prior_state: str,
    review_mismatches: Tuple[str, ...] = (),
    timeout_ms: int = 10000,
) -> SubmissionResult:
    """Submit a proven-ready LinkedIn or external ATS application."""
    if application_type == "LINKEDIN_EASY_APPLY":
        return submit_linkedin_application(
            page,
            live_submission_enabled=live_submission_enabled,
            prior_state=prior_state,
            review_mismatches=review_mismatches,
            timeout_ms=timeout_ms,
        )

    current_url = str(getattr(page, "url", "") or "")
    if prior_state != "SUBMIT_READY":
        return SubmissionResult(
            state="SUBMIT_BLOCKED",
            reason=f"invalid_prior_state:{prior_state or 'unknown'}",
            current_url=current_url,
        )
    if review_mismatches:
        return SubmissionResult(
            state="SUBMIT_BLOCKED",
            reason="review_mismatch",
            current_url=current_url,
        )
    if not live_submission_enabled:
        return SubmissionResult(
            state="SUBMIT_DISABLED",
            reason="live_submission_disabled",
            current_url=current_url,
        )

    submit, submit_text = _visible_submit_control(page, application_type)
    if submit is None:
        return SubmissionResult(
            state="SUBMIT_BLOCKED",
            reason="submit_control_not_found",
            current_url=current_url,
        )

    identity = _control_identity(submit)
    lowered = identity.lower()
    unsafe_tokens = (
        "withdraw",
        "cancel application",
        "discard",
        "close",
        "dismiss",
        "delete",
    )
    if any(token in lowered for token in unsafe_tokens):
        return SubmissionResult(
            state="SUBMIT_BLOCKED",
            reason=f"unsafe_submit_target:{identity or 'unknown'}",
            current_url=current_url,
        )

    actions = []
    try:
        try:
            submit.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        submit.click(timeout=5000)
        actions.append(f"clicked:{submit_text}")
    except Exception as exc:
        return SubmissionResult(
            state="SUBMIT_FAILED",
            reason=f"submit_click_failed:{type(exc).__name__}",
            current_url=str(getattr(page, "url", "") or current_url),
            actions=tuple(actions),
        )

    evidence = _wait_for_external_confirmation(
        page,
        before_url=current_url,
        timeout_ms=timeout_ms,
    )
    if not evidence:
        return SubmissionResult(
            state="SUBMIT_UNCONFIRMED",
            reason="confirmation_not_detected",
            current_url=str(getattr(page, "url", "") or current_url),
            actions=tuple(actions),
        )

    return SubmissionResult(
        state="CONFIRMED",
        confirmed=True,
        evidence=evidence,
        current_url=str(getattr(page, "url", "") or current_url),
        actions=tuple(actions),
    )


def submit_linkedin_application(
    page,
    *,
    live_submission_enabled: bool,
    prior_state: str,
    review_mismatches: Tuple[str, ...] = (),
    timeout_ms: int = 8000,
) -> SubmissionResult:
    """Submit only from a proven ready state and only with explicit live enablement."""
    current_url = getattr(page, "url", "")

    if prior_state != "SUBMIT_READY":
        return SubmissionResult(
            state="SUBMIT_BLOCKED",
            reason=f"invalid_prior_state:{prior_state or 'unknown'}",
            current_url=current_url,
        )

    if review_mismatches:
        return SubmissionResult(
            state="SUBMIT_BLOCKED",
            reason="review_mismatch",
            current_url=current_url,
        )

    if not live_submission_enabled:
        return SubmissionResult(
            state="SUBMIT_DISABLED",
            reason="live_submission_disabled",
            current_url=current_url,
        )

    submit, submit_text = _visible_submit_control(page, "LINKEDIN_EASY_APPLY")
    if submit is None:
        return SubmissionResult(
            state="SUBMIT_BLOCKED",
            reason="submit_control_not_found",
            current_url=current_url,
        )

    identity = _control_identity(submit)
    lowered = identity.lower()
    unsafe_tokens = ("withdraw", "cancel application", "discard", "close", "dismiss")
    if any(token in lowered for token in unsafe_tokens):
        return SubmissionResult(
            state="SUBMIT_BLOCKED",
            reason=f"unsafe_submit_target:{identity or 'unknown'}",
            current_url=current_url,
        )

    if identity and submit_text.lower() not in lowered:
        return SubmissionResult(
            state="SUBMIT_BLOCKED",
            reason=f"submit_target_mismatch:{identity}",
            current_url=current_url,
        )

    actions = []
    try:
        try:
            submit.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        submit.click(timeout=5000)
        actions.append(f"clicked:{submit_text}")
    except Exception as exc:
        return SubmissionResult(
            state="SUBMIT_FAILED",
            reason=f"submit_click_failed:{type(exc).__name__}",
            current_url=getattr(page, "url", current_url),
            actions=tuple(actions),
        )

    evidence = _wait_for_linkedin_confirmation(page, timeout_ms=timeout_ms)
    if not evidence:
        return SubmissionResult(
            state="SUBMIT_UNCONFIRMED",
            reason="confirmation_not_detected",
            current_url=getattr(page, "url", current_url),
            actions=tuple(actions),
        )

    return SubmissionResult(
        state="CONFIRMED",
        confirmed=True,
        evidence=evidence,
        current_url=getattr(page, "url", current_url),
        actions=tuple(actions),
    )


def record_confirmed_submission(store, job, result: SubmissionResult) -> bool:
    """Persist only a submission with positive confirmation evidence."""
    if not result.confirmed or result.state != "CONFIRMED" or not result.evidence:
        return False
    store.mark_submission_confirmed(
        job,
        application_method="agent",
        note=result.evidence,
    )
    return True
