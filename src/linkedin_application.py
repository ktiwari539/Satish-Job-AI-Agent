from dataclasses import dataclass, field
from typing import Optional

from application_engine import ApplicationStage, ApplicationStateMachine
from application_flow import ApplicationFlowResult, run_safe_application_flow
from apply_inspection import ApplicationEntryInspection, inspect_linkedin_application_entry


@dataclass(frozen=True)
class LinkedInApplicationRun:
    entry: ApplicationEntryInspection
    flow: Optional[ApplicationFlowResult] = None
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
    resume_path: str = "",
) -> LinkedInApplicationRun:
    """Run LinkedIn through the shared application state machine.

    This adapter does not treat clicks as progress. Entry/form transitions are
    recorded only when inspection confirms the expected state, while the
    existing safe form runner verifies each page transition.
    """
    machine = ApplicationStateMachine()

    entry = inspect_linkedin_application_entry(
        page,
        open_easy_apply=open_easy_apply,
        open_external_apply=open_external_apply,
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

        flow = run_safe_application_flow(
            page,
            profile,
            resume_path=resume_path,
            advance=advance_application,
            inspect_review=inspect_review,
        )
        _apply_flow_stage(machine, flow)

    return LinkedInApplicationRun(
        entry=entry,
        flow=flow,
        engine_stage=machine.stage.value,
        engine_history=_history(machine),
    )
