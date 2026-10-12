import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SUPPORTED_RESUME_SUFFIXES = {".pdf", ".doc", ".docx"}
DEFAULT_RESUME_DIR = Path.home() / ".satish-job-ai-agent" / "resume"
MANIFEST_NAME = "manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_resume(source_path: str, store_dir: str = str(DEFAULT_RESUME_DIR)) -> Path:
    """Import one trusted resume into the agent-owned local resume vault."""
    source = Path(source_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError("resume_source_not_found")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_RESUME_SUFFIXES:
        raise ValueError("unsupported_resume_type")

    target_dir = Path(store_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        target_dir.chmod(0o700)
    except OSError:
        pass

    digest = _sha256(source)
    target = target_dir / f"resume-{digest[:16]}{suffix}"
    if not target.exists():
        shutil.copy2(source, target)
    try:
        target.chmod(0o600)
    except OSError:
        pass

    manifest = {
        "current_file": target.name,
        "sha256": digest,
        "original_name": source.name,
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = target_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    try:
        manifest_path.chmod(0o600)
    except OSError:
        pass
    return target.resolve()


def resolve_current_resume(store_dir: str = str(DEFAULT_RESUME_DIR)) -> Path:
    """Return the current agent-owned resume, verifying it still matches the manifest."""
    target_dir = Path(store_dir).expanduser()
    manifest_path = target_dir / MANIFEST_NAME
    if not manifest_path.exists():
        raise FileNotFoundError("agent_resume_not_configured")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    current_file = str(payload.get("current_file", "") or "").strip()
    expected_hash = str(payload.get("sha256", "") or "").strip()
    if not current_file:
        raise ValueError("agent_resume_manifest_invalid")

    resume = target_dir / current_file
    if not resume.exists() or not resume.is_file():
        raise FileNotFoundError("agent_resume_file_missing")
    if resume.suffix.lower() not in SUPPORTED_RESUME_SUFFIXES:
        raise ValueError("agent_resume_type_invalid")
    if expected_hash and _sha256(resume) != expected_hash:
        raise ValueError("agent_resume_hash_mismatch")
    return resume.resolve()


def current_resume_metadata(store_dir: str = str(DEFAULT_RESUME_DIR)) -> dict:
    target_dir = Path(store_dir).expanduser()
    manifest_path = target_dir / MANIFEST_NAME
    if not manifest_path.exists():
        return {"configured": False}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        resolved = resolve_current_resume(store_dir)
        configured = True
        resolved_path: Optional[str] = str(resolved)
    except Exception as exc:
        configured = False
        resolved_path = None
        payload["validation_error"] = str(exc)
    payload["configured"] = configured
    payload["resolved_path"] = resolved_path
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage the agent-owned local resume vault.")
    parser.add_argument("--store-dir", default=str(DEFAULT_RESUME_DIR))
    sub = parser.add_subparsers(dest="command", required=True)

    import_parser = sub.add_parser("import", help="Import and select a trusted resume.")
    import_parser.add_argument("source_path")

    sub.add_parser("current", help="Show current resume metadata.")

    args = parser.parse_args()
    if args.command == "import":
        target = import_resume(args.source_path, args.store_dir)
        print(json.dumps({
            "status": "resume_imported",
            "agent_resume": str(target),
        }, sort_keys=True))
        return 0

    if args.command == "current":
        print(json.dumps(current_resume_metadata(args.store_dir), indent=2, sort_keys=True))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
