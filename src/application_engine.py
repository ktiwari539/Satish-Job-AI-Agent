from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class ApplicationStage(str, Enum):
    JOB_PAGE = "JOB_PAGE"
    AUTH = "AUTH"
    APPLICATION_ENTRY = "APPLICATION_ENTRY"
    APPLICATION_FORM = "APPLICATION_FORM"
    SCREENING = "SCREENING"
    RESUME = "RESUME"
    REVIEW = "REVIEW"
    SUBMIT = "SUBMIT"
    CONFIRMATION = "CONFIRMATION"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


_ALLOWED_TRANSITIONS: dict[ApplicationStage, set[ApplicationStage]] = {
    ApplicationStage.JOB_PAGE: {
        ApplicationStage.AUTH,
        ApplicationStage.APPLICATION_ENTRY,
        ApplicationStage.BLOCKED,
    },
    ApplicationStage.AUTH: {
        ApplicationStage.APPLICATION_ENTRY,
        ApplicationStage.BLOCKED,
    },
    ApplicationStage.APPLICATION_ENTRY: {
        ApplicationStage.APPLICATION_FORM,
        ApplicationStage.SCREENING,
        ApplicationStage.RESUME,
        ApplicationStage.REVIEW,
        ApplicationStage.BLOCKED,
    },
    ApplicationStage.APPLICATION_FORM: {
        ApplicationStage.APPLICATION_FORM,
        ApplicationStage.SCREENING,
        ApplicationStage.RESUME,
        ApplicationStage.REVIEW,
        ApplicationStage.BLOCKED,
    },
    ApplicationStage.SCREENING: {
        ApplicationStage.SCREENING,
        ApplicationStage.RESUME,
        ApplicationStage.REVIEW,
        ApplicationStage.BLOCKED,
    },
    ApplicationStage.RESUME: {
        ApplicationStage.SCREENING,
        ApplicationStage.REVIEW,
        ApplicationStage.BLOCKED,
    },
    ApplicationStage.REVIEW: {
        ApplicationStage.SUBMIT,
        ApplicationStage.APPLICATION_FORM,
        ApplicationStage.SCREENING,
        ApplicationStage.BLOCKED,
    },
    ApplicationStage.SUBMIT: {
        ApplicationStage.CONFIRMATION,
        ApplicationStage.BLOCKED,
    },
    ApplicationStage.CONFIRMATION: {
        ApplicationStage.COMPLETED,
        ApplicationStage.BLOCKED,
    },
    ApplicationStage.COMPLETED: set(),
    ApplicationStage.BLOCKED: set(),
}


@dataclass(frozen=True)
class StageTransition:
    previous: ApplicationStage
    current: ApplicationStage
    reason: str = ""


class InvalidApplicationTransition(RuntimeError):
    pass


class ApplicationStateMachine:
    """Portal-neutral application workflow state machine.

    Portal adapters may differ in selectors and page structure, but they must
    report real state transitions through this model. A click alone is never
    treated as progress.
    """

    def __init__(self, initial: ApplicationStage = ApplicationStage.JOB_PAGE) -> None:
        self._stage = initial
        self._history: list[StageTransition] = []

    @property
    def stage(self) -> ApplicationStage:
        return self._stage

    @property
    def history(self) -> tuple[StageTransition, ...]:
        return tuple(self._history)

    def can_transition(self, target: ApplicationStage) -> bool:
        return target in _ALLOWED_TRANSITIONS[self._stage]

    def transition(self, target: ApplicationStage, *, reason: str = "") -> StageTransition:
        if not self.can_transition(target):
            raise InvalidApplicationTransition(f"{self._stage.value}->{target.value}")
        event = StageTransition(self._stage, target, reason)
        self._stage = target
        self._history.append(event)
        return event

    def require_stage(self, allowed: Iterable[ApplicationStage]) -> None:
        allowed_set = set(allowed)
        if self._stage not in allowed_set:
            expected = ",".join(sorted(x.value for x in allowed_set))
            raise InvalidApplicationTransition(
                f"stage={self._stage.value}:expected_one_of={expected}"
            )
