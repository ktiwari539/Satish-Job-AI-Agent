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


def _visible_action(page, texts: tuple[str, ...]):
    for text in texts:
        selectors = (
            f"button:has-text('{text}')",
            f"[role='button']:has-text('{text}')",
            f"input[type='button'][value*='{text}']",
        )
        for selector in selectors:
            try:
                target = page.locator(selector).first
                if target.count() and target.is_visible() and target.is_enabled():
                    return target, text
            except Exception:
                continue
    return None, ""


def run_safe_application_flow(
    page,
    profile: dict,
    *,
    resume_path: str = "",
    advance: bool = False,
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
        actions.append(f"filled_known_fields:{len(plan.values)}")
        if plan.resume_path:
            actions.append("resume_uploaded")

        if any(
            reason in {
                "captcha_requires_human",
                "manual_auth_required",
                "answers_incomplete_or_unverified",
                "resume_upload_failed",
            }
            for reason in fill_reasons
        ):
            return ApplicationFlowResult(
                state="BLOCKED_AFTER_FILL",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=fill_reasons,
                actions=tuple(actions),
            )

        review, review_text = _visible_action(page, ("Review", "Review application"))
        if review is not None:
            actions.append(f"stopped_before:{review_text}")
            return ApplicationFlowResult(
                state="REVIEW_READY",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=plan.reasons,
                actions=tuple(actions),
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

        next_button, next_text = _visible_action(page, ("Next", "Continue"))
        if next_button is None:
            return ApplicationFlowResult(
                state="NO_SAFE_NEXT_ACTION",
                steps_completed=steps_completed,
                current_url=page.url,
                reasons=plan.reasons,
                actions=tuple(actions),
            )

        try:
            next_button.click(timeout=5000)
            page.wait_for_timeout(800)
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
