"""Local-only applicant city settings.

Never syncs applicant location or private profile contents to GitHub.
"""
import json
import os
import re
import tempfile
from pathlib import Path


def read_applicant_city(path: str) -> str:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("private_profile_must_be_object")
    return str(payload.get("location") or "").strip()


def set_applicant_city(path: str, city: str) -> str:
    """Safely set the existing local profile's application city only.

    Leaves other private profile fields unchanged. Never overwrites a
    missing profile, and writes atomically with owner-only permissions.
    """
    city = str(city or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]{0,79}", city):
        raise ValueError("invalid_applicant_city")
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("private_profile_must_be_object")
    payload["location"] = city
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".profile-city-",
            suffix=".tmp", dir=str(target.parent), delete=False,
        ) as handle:
            tmp_path = handle.name
            os.chmod(tmp_path, 0o600)
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
        os.chmod(target, 0o600)
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
    return city
