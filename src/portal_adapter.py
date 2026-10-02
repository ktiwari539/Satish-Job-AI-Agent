from dataclasses import dataclass
from typing import Protocol

from models import Job


@dataclass(frozen=True)
class LoginState:
    authenticated: bool
    needs_human_action: bool = False
    reason: str = ""


@dataclass(frozen=True)
class FormInspection:
    supported: bool
    required_unknown_fields: tuple[str, ...] = ()
    captcha_present: bool = False
    manual_auth_required: bool = False


class PortalAdapter(Protocol):
    portal_key: str

    def login_state(self) -> LoginState:
        ...

    def search(self, query: str, location: str = "") -> list[Job]:
        ...

    def inspect_application(self, job: Job) -> FormInspection:
        ...

    def fill_application(self, job: Job, profile: dict) -> FormInspection:
        ...

    def submit_application(self, job: Job) -> str:
        ...
