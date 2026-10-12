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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Securely configure local-only Job AI Agent credentials."
    )
    parser.add_argument("--file", default="data/portal_credentials.json")
    parser.add_argument(
        "--portal",
        default="external_default",
        choices=("external_default", "linkedin"),
    )
    parser.add_argument("--email", default="")
    args = parser.parse_args()

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
