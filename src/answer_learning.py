"""One-time, local-only learning for genuinely unknown required application facts.

Unknown applicant facts are never invented. During explicitly interactive QA,
the applicant may teach a truthful answer for the actual question visible in
the authenticated browser. Answers stay in the gitignored private profile.
The next fill/review attempt runs on the SAME open browser page.
"""
import json
import os
import tempfile
from pathlib import Path

from application_forms import resolve_profile_key
from browser_form_runtime import inspect_page_fields
from question_resolver import match_answer_to_option, normalize_question


def _store_private_answer_bank(path: str, profile: dict) -> None:
    original = Path(path)
    if not original.is_file():
        raise FileNotFoundError("private_profile_missing")
    # Atomic write; never leave a partially written profile if interrupted.
    fd, temp = tempfile.mkstemp(prefix=".answer_profile_", dir=str(original.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(profile, out, indent=2, ensure_ascii=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, original)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def learn_required_answers(page, profile: dict, profile_path: str,
                           unknown_fields) -> dict:
    """Ask for and store user-verified missing answers, without clicking Submit.

    This is an explicit interactive fallback, not an autonomous LLM. Each
    question is extracted from the *current* form and printed only in the
    user's local terminal. Never emit question or answer text to trace logs.
    """
    fields = inspect_page_fields(page)
    requested = {normalize_question(x) for x in unknown_fields}
    asked, saved, skipped = set(), 0, 0
    for field in fields:
        question = str(field.label or "").strip()
        normalized = normalize_question(question)
        if normalized not in requested or normalized in asked:
            continue
        asked.add(normalized)
        if len(normalized) < 6 or len(normalized) > 450:
            skipped += 1
            continue
        # Avoid relying on generic "field_3" or "Yes" as an employer prompt.
        if normalized in ("yes", "no", "required", "select an option"):
            skipped += 1
            continue
        if len(asked) > 12:
            skipped += 1
            continue
        # Never silently accept answers to demographic, legal or employment
        # questions. Every answer comes directly from the applicant.
        print("\nRequired question (LinkedIn): " + question, flush=True)
        if field.options:
            print("Available options: " + " / ".join(field.options[:30]), flush=True)
        try:
            entered = input("Your truthful answer (Enter=skip, :stop=end): ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if entered == ":stop":
            break
        if not entered:
            skipped += 1
            continue
        if field.options:
            matched = match_answer_to_option(entered, field.options)
            if not matched:
                print("The answer does not match a listed option; skipped.", flush=True)
                skipped += 1
                continue
            entered = matched
        bank = profile.setdefault("answers", {})
        if not isinstance(bank, dict):
            raise ValueError("private_answers_must_be_mapping")
        old = bank.get(question)
        bank[question] = entered
        try:
            _store_private_answer_bank(profile_path, profile)
        except (OSError, ValueError):
            if old is None:
                bank.pop(question, None)
            else:
                bank[question] = old
            raise
        saved += 1
        print("Verified answer saved privately for reuse.", flush=True)
    return {
        "questions_found": len(asked), "answers_saved": saved,
        "questions_skipped": skipped, "browser_kept_open": True,
        "submission_enabled": False,
    }
