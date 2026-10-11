from dataclasses import dataclass, field
from typing import Optional

from agent_trace import trace_event, trace_step
from application_engine import ApplicationStage, ApplicationStateMachine
from application_flow import ApplicationFlowResult, run_safe_application_flow
from apply_inspection import ApplicationEntryInspection, inspect_linkedin_application_entry
from submission_engine import SubmissionResult, submit_application


@dataclass(frozen=True)
class LinkedInApplicationRun:
    entry: ApplicationEntryInspection
    flow: Optional[ApplicationFlowResult] = None
    submission: Optional[SubmissionResult] = None
    engine_stage: str = ApplicationStage.JOB_PAGE.value
    engine_history: tuple[str, ...] = field(default_factory=tuple)


def _history(machine: ApplicationStateMachine) -> tuple[str, ...]:
    return tuple(
        f"{event.previous.value}->{event.current.value}:{event.reason}"
        for event in machine.history
    )


def _block(machine: ApplicationStateMachine, reason: str) -> None:
    if machine.stage != ApplicationStage.BLOCKED and machine.can_transition(ApplicationStage.BLOCKED):
        machine.transition(ApplicationStage.BLOCKED, reason=reason)


def _apply_flow_stage(machine: ApplicationStateMachine, flow: ApplicationFlowResult) -> None:
    state = flow.state

    if state.startswith("BLOCKED_") or state in {
        "NEXT_NO_TRANSITION",
        "NEXT_ACTION_FAILED",
        "NO_SAFE_NEXT_ACTION",
        "MAX_SAFE_STEPS_REACHED",
        "REVIEW_OPEN_FAILED",
        "REVIEW_VALIDATION_BLOCKED",
        "REVIEW_MISMATCH",
    }:
        if state.startswith("REVIEW_") and machine.can_transition(ApplicationStage.REVIEW):
            machine.transition(ApplicationStage.REVIEW, reason=state.lower())
        _block(machine, state.lower())
        return

    if state in {"REVIEW_READY", "REVIEW_INSPECTED"}:
        if machine.can_transition(ApplicationStage.REVIEW):
            machine.transition(ApplicationStage.REVIEW, reason=state.lower())
        return

    if state == "SUBMIT_READY":
        if machine.can_transition(ApplicationStage.REVIEW):
            machine.transition(ApplicationStage.REVIEW, reason="review_stage_reached")
        if machine.can_transition(ApplicationStage.SUBMIT):
            machine.transition(ApplicationStage.SUBMIT, reason="submit_control_verified")
        return

    if state == "FILLED_CURRENT_STEP":
        # Filling a page is not progress by itself. Keep the current stage.
        return


def run_linkedin_application(
    page,
    profile: Optional[dict] = None,
    *,
    open_easy_apply: bool = False,
    open_external_apply: bool = False,
    fill_application: bool = False,
    advance_application: bool = False,
    inspect_review: bool = False,
    submit_application: bool = False,
    live_submission_enabled: bool = False,
    resume_path: str = "",
) -> LinkedInApplicationRun:
    """Run LinkedIn through the shared application state machine.

    This adapter does not treat clicks as progress. Entry/form transitions are
    recorded only when inspection confirms the expected state, while the
    existing safe form runner verifies each page transition.
    """
    machine = ApplicationStateMachine()
    trace_event(
        "linkedin_application_start",
        current_url=str(getattr(page, "url", "") or ""),
        open_easy_apply=open_easy_apply,
        open_external_apply=open_external_apply,
        fill_application=fill_application,
        advance_application=advance_application,
        inspect_review=inspect_review,
        submit_application=submit_application,
        live_submission_enabled=live_submission_enabled,
    )

    with trace_step("application_entry_inspection"):
        entry = inspect_linkedin_application_entry(
        page,
        open_easy_apply=open_easy_apply,
            open_external_apply=open_external_apply,
        )
    trace_event(
        "linkedin_application_entry",
        application_type=entry.application_type,
        application_state=entry.application_state,
        ats_provider=entry.ats_provider,
        opened=entry.opened,
        field_count=entry.field_count,
        required_field_count=entry.required_field_count,
        reason=entry.reason,
        current_url=entry.url,
    )

    if entry.application_state == "FORM_READY":
        machine.transition(
            ApplicationStage.APPLICATION_ENTRY,
            reason=f"{entry.application_type.lower()}_entry_confirmed",
        )
        machine.transition(
            ApplicationStage.APPLICATION_FORM,
            reason="application_form_verified",
        )
    elif entry.application_state == "APPLICATION_ENTRY_FOUND":
        machine.transition(
            ApplicationStage.APPLICATION_ENTRY,
            reason=f"{entry.application_type.lower()}_entry_confirmed",
        )
    else:
        _block(machine, entry.reason or entry.application_state.lower())

    flow = None
    if (
        fill_application
        and entry.application_state == "FORM_READY"
        and machine.stage == ApplicationStage.APPLICATION_FORM
    ):
        if profile is None:
            raise ValueError("private_profile_required_for_fill")

        with trace_step("safe_application_flow"):
            flow = run_safe_application_flow(
                page,
                profile,
                resume_path=resume_path,
                advance=advance_application,
                inspect_review=inspect_review,
                live_submission_enabled=live_submission_enabled,
                application_type=entry.application_type,
            )
        trace_event(
            "safe_application_flow_result",
            state=flow.state,
            steps_completed=flow.steps_completed,
            reasons=list(flow.reasons),
            unknown_required_fields=list(flow.unknown_required_fields),
            missing_profile_values=list(flow.missing_profile_values),
            review_mismatches=list(flow.review_mismatches),
            current_url=flow.current_url,
        )
        _apply_flow_stage(machine, flow)

    submission = None
    if (
        flow is not None
        and flow.state == "SUBMIT_READY"
        and submit_application
    ):
        submission = submit_application(
            page,
            application_type=entry.application_type,
            live_submission_enabled=live_submission_enabled,
            prior_state="SUBMIT_READY",
            review_mismatches=flow.review_mismatches,
        )
        if submission.confirmed:
            if machine.stage == ApplicationStage.SUBMIT:
                machine.transition(
                    ApplicationStage.CONFIRMATION,
                    reason="positive_submission_confirmation_detected",
                )
                machine.transition(
                    ApplicationStage.COMPLETED,
                    reason="submission_confirmed",
                )
        else:
            _block(machine, submission.reason or submission.state.lower())

    trace_event(
        "linkedin_application_end",
        engine_stage=machine.stage.value,
        engine_history=list(_history(machine)),
        flow_state=flow.state if flow is not None else "",
        submission_state=submission.state if submission is not None else "",
    )
    return LinkedInApplicationRun(
        entry=entry,
        flow=flow,
        submission=submission,
        engine_stage=machine.stage.value,
        engine_history=_history(machine),
    )
