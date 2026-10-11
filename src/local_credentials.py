import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PortalCredentials:
    email: str
    password: str

    def complete(self) -> bool:
        return bool(self.email.strip() and self.password)


def load_portal_credentials(path: str, portal: str) -> PortalCredentials:
    """Load one portal's credentials from a local, gitignored JSON file."""
    target = Path(path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("portal_credentials_file_not_found")

    payload = json.loads(target.read_text(encoding="utf-8"))
    entry = payload.get(portal, {}) if isinstance(payload, dict) else {}
    if not isinstance(entry, dict):
        raise ValueError("portal_credentials_entry_invalid")

    credentials = PortalCredentials(
        email=str(entry.get("email", "") or "").strip(),
        password=str(entry.get("password", "") or ""),
    )
    if not credentials.complete():
        raise ValueError("portal_credentials_incomplete")
    return credentials


def load_first_portal_credentials(path: str, portals: tuple[str, ...]) -> PortalCredentials:
    """Load the first complete credential entry from an ordered local-only list."""
    target = Path(path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("portal_credentials_file_not_found")

    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("portal_credentials_file_invalid")

    for portal in portals:
        entry = payload.get(portal, {})
        if not isinstance(entry, dict):
            continue
        credentials = PortalCredentials(
            email=str(entry.get("email", "") or "").strip(),
            password=str(entry.get("password", "") or ""),
        )
        if credentials.complete():
            return credentials

    raise ValueError("portal_credentials_incomplete")
