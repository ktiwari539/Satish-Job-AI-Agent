"""Import user-exported Naukri/Indeed jobs; never control a browser or apply."""
import argparse
import copy
import json
import os
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from auth_bridge import AuthProvider, AuthProviderUnavailable
from automation_policy import load_automation_policy
from models import CandidateProfile
from naukri_browser_import import evaluate_export, MAX_EXPORT_BYTES
from portal_export_urls import canonical_export_job_url
from profile_consistency import verify_profile_consistency
from sheet_control import load_requested_control, control_stop_reason, restrictive_control_limits, ControlSheetError
from store import JobStore


def validate_capture(payload, *, now=None):
    if not isinstance(payload, dict) or type(payload.get('schema_version')) is not int or payload['schema_version'] != 1:
        raise ValueError('unsupported_capture_schema')
    portal = payload.get('portal')
    if portal not in ('naukri', 'indeed'):
        raise ValueError('unsupported_capture_portal')
    try:
        captured = datetime.fromisoformat(str(payload.get('captured_at', '')).replace('Z', '+00:00'))
        current = now or datetime.now(timezone.utc)
        if captured.tzinfo is None or not -120 <= (current - captured).total_seconds() <= 86400:
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        raise ValueError('capture_timestamp_stale_or_invalid') from None
    data = copy.deepcopy(payload)
    rows = data.get('jobs')
    if isinstance(rows, list) and not rows:
        raise ValueError('capture_has_no_verified_job_links')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 75:
        raise ValueError('invalid_capture_job_count')
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('invalid_capture_job')
        canonical = canonical_export_job_url(portal, row.get('url'))
        if not canonical:
            raise ValueError('invalid_capture_job_identity')
        row['url'] = canonical
    inspection = data.pop('application_inspection', None)
    if inspection is not None:
        if (not isinstance(inspection, dict) or inspection.get('schema_version') != 2
                or inspection.get('portal') != portal or inspection.get('mode') != 'READ_ONLY_INSPECTION'
                or data.get('page_kind') != 'detail' or len(rows) != 1
                or canonical_export_job_url(portal, inspection.get('job_url')) != rows[0]['url']):
            raise ValueError('inspection_job_identity_mismatch')
        actions = inspection.get('application_controls', [])
        allowed = {'already_applied', 'external_apply', 'apply', 'submit', 'next_or_review', 'login'}
        if not isinstance(actions, list) or len(actions) > 6 or any(not isinstance(x, str) or x not in allowed for x in actions):
            raise ValueError('invalid_inspection_controls')
        flags = {}
        for key in ('captcha_present', 'otp_present', 'account_login_present'):
            if type(inspection.get(key)) is not bool:
                raise ValueError('invalid_inspection_challenge_flags')
            flags[key] = inspection[key]
        # Only the exact job and categorical evidence enter the local report.
        data['application_inspection'] = dict(job_url=rows[0]['url'], application_controls=sorted(set(actions)),
                                             **flags, submission_enabled=False, application_ready=False)
    return data


def evaluate_capture(payload, profile, private_profile, policy, store, *, now=None):
    verify_profile_consistency(profile, private_profile)
    data = validate_capture(payload, now=now)
    report = evaluate_export(data, profile, policy, store, portal=data['portal'])
    report.update(verification_scope='user_exported_job_data', application_ready=False,
                  submission_enabled=False, private_profile_consistency_checked=True,
                  captured_at=data['captured_at'])
    if 'application_inspection' in data:
        report['application_inspection'] = data['application_inspection']
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', required=True)
    parser.add_argument('--profile', default='config/qa_profile.json')
    parser.add_argument('--private-profile', default='data/private_profile.json')
    parser.add_argument('--policy', default='config/automation_policy.production.json')
    parser.add_argument('--db', default='data/jobs.db')
    parser.add_argument('--report', default='data/chrome_job_import_report.json')
    parser.add_argument('--control-workbook', default='')
    parser.add_argument('--use-control-sheet', action='store_true')
    parser.add_argument('--auth-config', default='data/auth_bridge.json')
    args = parser.parse_args()
    try:
        profile = CandidateProfile.from_dict(json.loads(Path(args.profile).read_text()))
        private = json.loads(Path(args.private_profile).read_text())
        if not isinstance(private, dict):
            raise ValueError('private_profile_must_be_an_object')
        provider = AuthProvider(args.auth_config) if args.use_control_sheet else None
        profile, private, control = load_requested_control(args, provider, profile, private)
        verify_profile_consistency(profile, private)
        if control_stop_reason(control):
            result = dict(status='control_agent_paused', control=control.diagnostics(),
                          submission_enabled=False, application_ready=False, submitted=0, confirmed=0)
            code = 4
        else:
            path = Path(args.file).expanduser()
            if not path.is_file() or path.stat().st_size > MAX_EXPORT_BYTES:
                raise ValueError('capture_file_missing_or_oversized')
            payload = json.loads(path.read_text())
            policy = load_automation_policy(args.policy)
            if control is not None:
                threshold, _ = restrictive_control_limits(control, policy.threshold, policy.daily_success_cap)
                policy = replace(policy, threshold=threshold)
            # Validate before opening the ledger. No browser/session is imported.
            payload = validate_capture(payload)
            result = evaluate_capture(payload, profile, private, policy, JobStore(args.db))
            result['status'] = 'imported_for_review'
            if control is not None:
                result['control'] = control.diagnostics()
            code = 0
    except (OSError, ValueError, AuthProviderUnavailable) as exc:
        reason = str(exc) if isinstance(exc, (ValueError, AuthProviderUnavailable)) else 'local_configuration_or_capture_unavailable'
        if not re.fullmatch('[a-z][a-z0-9_]{0,120}', reason):
            reason = 'local_configuration_or_capture_invalid'
        if isinstance(exc, json.JSONDecodeError):
            reason = 'local_json_invalid'
        result = dict(status='chrome_import_requires_review', reason_code=reason[:160],
                      fields=list(getattr(exc, 'fields', ())), submission_enabled=False,
                      application_ready=False, submitted=0, confirmed=0)
        code = 2
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True))
    os.replace(temporary, target)
    # Job titles/JDs and private facts remain in the local report, not stdout.
    print(json.dumps({key: result[key] for key in ('status', 'reason_code', 'fields', 'portal', 'discovered',
          'full_jd', 'qualified', 'needing_full_jd', 'submission_enabled', 'application_ready', 'submitted', 'confirmed')
          if key in result}, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
