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
