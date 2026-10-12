import argparse
import getpass
import json
import os
from pathlib import Path


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def save_credentials(
    path: str,
    portal: str,
    email: str,
    password: str,
) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _load(target)
    payload[portal] = {
        "email": email.strip(),
        "password": password,
    }
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(target)
    os.chmod(target, 0o600)
    return target.resolve()


def remove_credentials(path: str, portal: str) -> bool:
    """Remove one obsolete portal entry without touching other accounts."""
    target = Path(path).expanduser()
    if not target.exists():
        return False
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("credential_file_unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError("credential_file_invalid")
    if portal not in payload:
        return False
    del payload[portal]
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(target)
    os.chmod(target, 0o600)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Securely configure local-only Job AI Agent credentials."
    )
    parser.add_argument("--file", default="data/portal_credentials.json")
    parser.add_argument(
        "--portal",
        default="external_default",
        choices=("external_default", "linkedin", "naukri"),
    )
    parser.add_argument("--email", default="")
    parser.add_argument("--remove", action="store_true", help="Remove credentials for the selected portal")
    args = parser.parse_args()

    if args.remove:
        try:
            removed = remove_credentials(args.file, args.portal)
        except ValueError as exc:
            print(json.dumps({"status": "removal_failed", "reason": str(exc)}))
            return 2
        print(json.dumps({"status": "credentials_removed" if removed else "already_absent", "portal": args.portal}))
        return 0

    email = args.email.strip() or input("Email: ").strip()
    if not email:
        print(json.dumps({"status": "email_required"}))
        return 2

    password = getpass.getpass("Password (input hidden): ")
    if not password:
        print(json.dumps({"status": "password_required"}))
        return 2

    target = save_credentials(args.file, args.portal, email, password)
    print(json.dumps({
        "status": "credentials_saved",
        "portal": args.portal,
        "file": str(target),
        "permissions": "0600",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
