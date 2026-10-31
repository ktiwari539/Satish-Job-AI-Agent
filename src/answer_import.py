"""Import applicant-reviewed, job-scoped answers without browser or submission IO."""
import json
import re
from pathlib import Path

from answer_learning import _store_private_answer_bank
from question_resolver import normalize_question


class AnswerImportError(ValueError):
    """A safe category, never an exception containing a private path/value."""
    def __init__(self, code):
        self.code=code
        super().__init__(code)


def _read_object(path, kind):
    target = Path(path)
    try:
        if target.stat().st_size > 1000000:
            raise AnswerImportError(kind+'_too_large')
        raw=target.read_text(encoding='utf-8')
    except FileNotFoundError:
        raise AnswerImportError(kind+'_missing') from None
    except (OSError,UnicodeError):
        raise AnswerImportError(kind+'_unreadable') from None
    try:value=json.loads(raw)
    except ValueError:raise AnswerImportError(kind+'_invalid_json') from None
    if not isinstance(value, dict):
        raise AnswerImportError(kind+'_object_required')
    return value


def import_reviewed_answers(profile_path, answers_path):
    """Keep explicit answers verbatim and scoped to their original job.

    Importing a fact is not evidence that a portal accepted it. Runtime option
    matching, field validation, Sheet decisions and approval gates still apply.
    Validate the entire batch before the single atomic private-profile write.
    """
    payload = _read_object(answers_path,'reviewed_answers_file')
    if set(payload) != {'schema_version', 'answers'} or payload['schema_version'] != 1:
        raise AnswerImportError('answer_import_schema_invalid')
    rows = payload['answers']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise AnswerImportError('answer_import_rows_invalid')
    profile = _read_object(profile_path,'private_profile')
    if any(str(key).startswith('_control_') for key in profile):
        raise AnswerImportError('private_profile_contains_transient_controls')
    banks = profile.get('job_answers', {})
    if not isinstance(banks, dict) or any(not isinstance(bank, dict) for bank in banks.values()):
        raise AnswerImportError('private_job_answers_must_be_mapping')
    banks = {key: dict(bank) for key, bank in banks.items()}
    seen = {}; added = replaced = unchanged = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'source', 'job_id', 'question', 'answer'}:
            raise AnswerImportError('answer_import_record_invalid')
        if any(not isinstance(value, str) for value in row.values()):
            raise AnswerImportError('answer_import_string_required')
        source, job_id, question, answer = (row[key].strip() for key in ('source', 'job_id', 'question', 'answer'))
        if source not in ('linkedin', 'naukri', 'indeed', 'greenhouse', 'lever', 'workday') or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', job_id):
            raise AnswerImportError('answer_import_job_invalid')
        if not 6 <= len(question) <= 450 or not 1 <= len(answer) <= 2000:
            raise AnswerImportError('answer_import_text_invalid')
        if re.search(r'\b(password|passcode|otp|verification code|access token)\b', question, re.I):
            raise AnswerImportError('answer_import_secret_prompt_rejected')
        scope = source + ':' + job_id
        normalized = normalize_question(question)
        key = (scope, normalized)
        if key in seen:
            if seen[key] != answer: raise AnswerImportError('answer_import_conflicting_duplicates')
            unchanged += 1
            continue
        seen[key] = answer
        bank = banks.setdefault(scope, {})
        matches = [key for key in bank if normalize_question(key) == normalized]
        if len(matches) == 1 and matches[0] == question and bank[question] == answer:
            unchanged += 1
            continue
        if matches: replaced += 1
        else: added += 1
        for key in matches: del bank[key]
        bank[question] = answer
    if added or replaced:
        try:_store_private_answer_bank(profile_path, {**profile, 'job_answers': banks})
        except OSError:raise AnswerImportError('private_profile_write_failed') from None
    return dict(added=added, replaced=replaced, unchanged=unchanged,
                submission_enabled=False, submitted=0)
