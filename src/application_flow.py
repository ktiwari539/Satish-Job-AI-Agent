from dataclasses import dataclass, field

from browser_form_runtime import apply_fill_plan, build_page_fill_plan


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
        ".artdeco-modal[role='dialog']",
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
                f"button:has-text('{text}')",
                f"[role='button']:has-text('{text}')",
                f"button[aria-label*='{text}']",
                f"[role='button'][aria-label*='{text}']",
                f"input[type='button'][value*='{text}']",
            ))
        for selector in selectors:
            try:
                target = page.locator(selector).first
                if target.count() and target.is_visible() and target.is_enabled():
                    return target, text
            except Exception:
                continue
    return None, ""



def _application_step_signature(page) -> str:
    """Stable signature for the currently visible Easy Apply step."""
    script = """
    () => {
      const roots = [
        '.jobs-easy-apply-modal',
        '.artdeco-modal[role="dialog"]',
        '[role="dialog"]'
      ];
      const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          rect.width > 0 && rect.height > 0;
      };
      const root = roots.map((s) => document.querySelector(s)).find(visible);
      if (!root) return '';

      const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
      const progress = Array.from(root.querySelectorAll(
        '[role="progressbar"], progress, [aria-valuenow], [class*="progress"]'
      )).filter(visible).map((el) => [
        clean(el.getAttribute('aria-valuenow')),
        clean(el.getAttribute('aria-valuetext')),
        clean(el.innerText || el.textContent)
      ].join(':')).join('|');

      const headings = Array.from(root.querySelectorAll(
        'h1, h2, h3, legend, .fb-dash-form-element__label'
      )).filter(visible).map((el) => clean(el.innerText || el.textContent))
        .filter(Boolean).slice(0, 12).join('|');

      const controls = Array.from(root.querySelectorAll('input, textarea, select'))
        .filter((el) => !el.disabled && (el.type || '').toLowerCase() !== 'hidden')
        .map((el) => {
          const id = el.id || '';
          let label = '';
          if (id) {
            const node = document.querySelector('label[for="' + CSS.escape(id) + '"]');
            if (node) label = clean(node.innerText || node.textContent);
          }
          return [
            (el.tagName || '').toLowerCase(),
            (el.type || '').toLowerCase(),
            el.name || '',
            id,
            label
          ].join(':');
        }).join('|');

      const actions = Array.from(root.querySelectorAll('button, [role="button"]'))
        .filter(visible)
        .map((el) => clean(el.innerText || el.textContent || el.getAttribute('aria-label')))
        .filter(Boolean).join('|');

      return [progress, headings, controls, actions].join('||');
    }
    """
    try:
        return str(page.evaluate(script) or "")
    except Exception:
        return ""


def _wait_for_step_transition(page, before: str, timeout_ms: int = 3500) -> bool:
    if not before:
        return True
    elapsed = 0
    interval = 250
    while elapsed < timeout_ms:
        page.wait_for_timeout(interval)
        elapsed += interval
        after = _application_step_signature(page)
        if after and after != before:
            return True
    return False


def _click_action(target) -> None:
    """Click a visible navigation control with browser-native fallbacks."""
    try:
        target.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass

    errors = []
    for force, timeout in ((False, 5000), (True, 2500)):
        try:
            target.click(force=force, timeout=timeout)
            return
        except Exception as exc:
            errors.append(exc)

    # Playwright can time out while an otherwise enabled LinkedIn button is
    # continuously re-rendered.  A DOM click on the already-resolved element is
    # safe here because submit controls are handled separately and never passed
    # to this helper.
    try:
        target.evaluate("(el) => el.click()")
        return
    except Exception as exc:
        errors.append(exc)

    raise errors[-1]




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
    return tuple(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))


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

    for key in ("email", "phone", "full_name", "linkedin"):
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


def run_safe_application_flow(
    page,
    profile: dict,
    *,
    resume_path: str = "",
    advance: bool = False,
    inspect_review: bool = False,
    max_steps: int = 6,
) -> ApplicationFlowResult:
    actions: list[str] = []
    steps_completed = 0

    for _ in range(max_steps):
        plan = build_page_fill_plan(
            page,
            profile,
            resume_path=resume_path,
            live_submission_enabled=False,
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

        fill_reasons = apply_fill_plan(page, plan)
        actions.append(f"planned_known_fields:{len(plan.values)}")
        if plan.resume_path:
            actions.append("resume_uploaded")

        if any(
            reason in {
                "captcha_requires_human",
                "manual_auth_required",
                "answers_incomplete_or_unverified",
                "resume_upload_failed",
            }
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
            if not inspect_review:
                actions.append(f"stopped_before:{review_text}")
                return ApplicationFlowResult(
                    state="REVIEW_READY",
                    steps_completed=steps_completed,
                    current_url=page.url,
                    reasons=plan.reasons,
                    actions=tuple(actions),
                )

            try:
                _click_action(review)
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

            submit, submit_text = _visible_action(
                page,
                ("Submit application", "Submit", "Apply now", "Send application"),
            )
            try:
                body_after_review = page.locator("body").inner_text(timeout=3000).lower()
            except Exception:
                body_after_review = ""

            if submit is None and "this field is required" in body_after_review:
                actions.append("review_validation_blocked")
                return ApplicationFlowResult(
                    state="REVIEW_VALIDATION_BLOCKED",
                    steps_completed=steps_completed,
                    current_url=page.url,
                    reasons=plan.reasons,
                    actions=tuple(actions),
                    visible_actions=_visible_action_texts(page),
                )

            review_checks, review_mismatches = _inspect_review(page, profile)
            if submit is not None:
                actions.append(f"stopped_before:{submit_text}")
            else:
                actions.append("review_opened_no_submit_clicked")

            return ApplicationFlowResult(
                state="REVIEW_INSPECTED" if not review_mismatches else "REVIEW_MISMATCH",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=plan.reasons,
                actions=tuple(actions),
                review_checks=review_checks,
                review_mismatches=review_mismatches,
            )

        submit, submit_text = _visible_action(
            page,
            ("Submit application", "Submit", "Apply now", "Send application"),
        )
        if submit is not None:
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
        if next_button is None:
            return ApplicationFlowResult(
                state="NO_SAFE_NEXT_ACTION",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=plan.reasons,
                actions=tuple(actions),
                visible_actions=_visible_action_texts(page),
            )

        before_step = _application_step_signature(page)
        try:
            _click_action(next_button)
            if not _wait_for_step_transition(page, before_step):
                return ApplicationFlowResult(
                    state="NEXT_NO_TRANSITION",
                    steps_completed=steps_completed,
                    current_url=page.url,
                    reasons=("next_click_did_not_change_easy_apply_step",),
                    actions=tuple(actions + [f"clicked_no_transition:{next_text}"]),
                    visible_actions=_visible_action_texts(page),
                )
            steps_completed += 1
            actions.append(f"clicked:{next_text}")
        except Exception as exc:
            return ApplicationFlowResult(
                state="NEXT_ACTION_FAILED",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=(f"next_click_failed:{type(exc).__name__}",),
                actions=tuple(actions),
            )

    return ApplicationFlowResult(
        state="MAX_SAFE_STEPS_REACHED",
        steps_completed=steps_completed,
        current_url=page.url,
        actions=tuple(actions),
    )
