"""Bounded cross-portal discovery, qualification and verified form preparation.

This workflow never submits. Portal-specific live certification and exact-job
submission approval remain distinct from generic form preparation.
"""
import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from agent_trace import RunTracer, set_active_tracer, reset_active_tracer
from browser_qa import inspect_portal_session, extract_current_jobs
from browser_portals import LinkedInBrowserAdapter, NaukriBrowserAdapter
from browser_runtime import BrowserRuntimeConfig, BrowserRuntimeUnavailable, PlaywrightSession
from jd_enrichment import EnrichmentResult
from models import CandidateProfile
from navigation import bounded_goto
from portal_catalog import PORTAL_TARGETS, build_search_url
from portal_preparation import prepare_portal_job, exact_job_page
from review_runner import prepare_review_batch, ReviewPreparationResult
from resume_store import resolve_current_resume
from sources import discover_greenhouse, discover_lever
from store import JobStore
from profile_consistency import verify_profile_consistency, ProfileFactsConflict
from preparation_revision import preparation_revision
from application_forms import validate_resume_path
from live_blocker_capture import capture_blocker
from verified_jd import read_verified_job_description
from auth_bridge import AuthProvider, AuthProviderUnavailable
from portal_session import ensure_portal_session, auth_structure


DISCOVERY_PORTALS = ('linkedin', 'naukri', 'indeed', 'greenhouse', 'lever')


def _require_open_browser(page):
    try:
        closed = page.is_closed()
    except Exception as exc:
        raise BrowserRuntimeUnavailable('Browser connection lost.', reason_code='browser_connection_lost') from exc
    if closed:
        raise BrowserRuntimeUnavailable('Browser closed during the run.', reason_code='browser_connection_lost')


def _discover_public_portal(portal, config_path, taxonomy):
    config = json.loads(Path(config_path).read_text())
    key, discover = ('greenhouse_boards', discover_greenhouse) if portal == 'greenhouse' else ('lever_sites', discover_lever)
    targets = config.get(key, [])
    if not isinstance(targets, list):
        raise ValueError('public_source_configuration_must_be_a_list')
    found, failures = [], []
    for target in targets[:5]:
        if not isinstance(target, str) or not target.strip():
            failures.append(dict(reason_code='invalid_source_configuration'))
            continue
        try:
            found.extend(discover(target, taxonomy))
        except Exception as exc:
            failures.append(dict(reason_code=type(exc).__name__))
    return found, failures


def _wait_for_job_cards(page, portal, taxonomy):
    for attempt in range(13):
        _require_open_browser(page)
        jobs = extract_current_jobs(page, portal, taxonomy)
        if jobs or attempt == 12:
            return jobs
        page.wait_for_timeout(250)


def run_on_page(page, args, profile, private_profile, store, *, auth_provider=None):
    jobs, portal_results = [], []
    verify_profile_consistency(profile, private_profile)
    for portal in args.portals:
        _require_open_browser(page)
        if portal not in DISCOVERY_PORTALS:
            portal_results.append(dict(portal=portal, status='DISCOVERY_ADAPTER_UNVERIFIED', discovered=0))
            continue
        try:
            if portal in ('greenhouse', 'lever'):
                if not args.sources:
                    portal_results.append(dict(portal=portal, status='SOURCE_CONFIGURATION_REQUIRED', discovered=0))
                    continue
                found, source_failures = _discover_public_portal(portal, args.sources, profile.skill_taxonomy)
            else:
                if portal in ('linkedin', 'naukri'):
                    adapter = LinkedInBrowserAdapter(page) if portal == 'linkedin' else NaukriBrowserAdapter(page)
                    login = adapter.login_state()
                    authenticated = login.authenticated and not login.needs_human_action
                else:
                    authenticated = inspect_portal_session(page, portal).status == 'SESSION_CONFIRMED'
                auth_evidence = None
                if not authenticated:
                    if auth_provider is not None:
                        auth = ensure_portal_session(page,portal,auth_provider,
                            allow_login=not getattr(args,'no_login',False),otp_mode=getattr(args,'otp_mode','auto'))
                        _require_open_browser(page)
                        authenticated = auth.authenticated
                        auth_evidence = asdict(auth)
                    if not authenticated:
                        portal_results.append(dict(portal=portal,
                            status=auth_evidence['state'] if auth_evidence else 'SESSION_REQUIRED',
                            authentication=auth_evidence,authentication_probe=auth_structure(page),discovered=0))
                        continue
                if portal in ('linkedin', 'naukri'):
                    adapter.open_search(args.query, args.location)
                else:
                    bounded_goto(page, build_search_url(portal, args.query, args.location))
                found = _wait_for_job_cards(page, portal, profile.skill_taxonomy)
            selected = found[:args.max_jobs]
            jobs.extend(selected)
            row = dict(portal=portal, status='DISCOVERED' if selected else 'NO_VERIFIED_JOB_CARDS', discovered=len(selected))
            if portal in ('greenhouse', 'lever'):
                row.update(source_failures=source_failures, source_limit=5)
            elif auth_evidence is not None:
                row['authentication'] = auth_evidence
            portal_results.append(row)
        except BrowserRuntimeUnavailable:
            raise
        except Exception as exc:
            _require_open_browser(page)
            portal_results.append(dict(portal=portal, status='DISCOVERY_BLOCKED', reason_code=type(exc).__name__, discovered=0))
    evidence, jd_evidence = [], []
    def enrich(job):
        _require_open_browser(page)
        try:
            bounded_goto(page, job.url)
        except Exception:
            _require_open_browser(page)
            raise
        _require_open_browser(page)
        if not exact_job_page(page, job):
            jd_evidence.append(dict(job_key=job.key,source=job.source,reason='job_identity_or_authentication_unverified'))
            return EnrichmentResult(job, False, 'job_identity_or_authentication_unverified')
        result, diagnostic = read_verified_job_description(page,job,profile.skill_taxonomy,
            allow_public_fallback=getattr(args,'public_jd_fallback',False))
        if not result.enriched:
            diagnostic['blocker_report'] = capture_blocker(page,stage='job_description',
                outcome='SKIPPED_JD',reason_code=result.reason)
        jd_evidence.append(diagnostic)
        return result
    def prepare(job, facts):
        _require_open_browser(page)
        try:
            result = prepare_portal_job(page, job, dict(facts), resume_path=args.resume_path,
                                       applicant_experience_years=profile.total_experience_years)
        except Exception:
            _require_open_browser(page)
            raise
        _require_open_browser(page)
        item = dict(job_key=job.key, source=job.source, **asdict(result))
        if result.state != 'READY_FOR_REVIEW':
            item['blocker_report'] = capture_blocker(page, stage='cross_portal_preparation',
                outcome=result.flow_state, reason_code=result.reason)
        if result.reason == 'already_applied_on_portal':
            store.mark_applied(job, application_method='portal_observed', note='positive_exact_job_applied_indicator')
        evidence.append(item)
        return ReviewPreparationResult(result.state, result.reason)
    try:
        batch = prepare_review_batch(jobs, profile=profile, private_profile=private_profile,
            threshold=args.threshold, cooldown_days=90, store=store, enrich_job=enrich,
            prepare_job=prepare, dedupe_within_batch=True,
            preparation_revision=preparation_revision(asdict(profile), private_profile, args.resume_path))
    except BrowserRuntimeUnavailable as exc:
        return dict(status='cross_portal_environment_blocked', **exc.diagnostics(),
            portal_results=portal_results, application_evidence=evidence, jd_evidence=jd_evidence, partial_results=True,
            submitted=0, confirmed=0, submission_enabled=False, acceptance_passed=False)
    return dict(status='cross_portal_preparation_complete', verification_scope='local_authenticated_portals_required',
        query=args.query, portal_results=portal_results, preparation=asdict(batch),
        application_evidence=evidence, submission_enabled=False, submitted=0, confirmed=0,
        jd_evidence=jd_evidence,
        live_portal_certification=False, acceptance_passed=False, submission_approval_required=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--portals', default='linkedin,naukri,indeed')
    parser.add_argument('--query', default='')
    parser.add_argument('--location', default='India')
    parser.add_argument('--max-jobs', type=int, choices=range(1,21), default=10)
    parser.add_argument('--profile', default='config/qa_profile.json')
    parser.add_argument('--private-profile', default='data/private_profile.json')
    parser.add_argument('--profile-dir', default='browser-profile')
    parser.add_argument('--resume-path', default='')
    parser.add_argument('--sources', default='')
    parser.add_argument('--db', default='data/jobs.db')
    parser.add_argument('--report', default='data/certification/portals.json')
    parser.add_argument('--threshold', type=int, choices=range(75,101), default=75)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--auth-config',default='data/auth_bridge.json')
    parser.add_argument('--credentials-file',default='data/portal_credentials.json')
    parser.add_argument('--no-login',action='store_true')
    parser.add_argument('--otp-mode',choices=('auto','manual','none'),default='auto')
    parser.add_argument('--no-public-jd-fallback',dest='public_jd_fallback',action='store_false',default=True)
    args = parser.parse_args()
    args.portals = tuple(PORTAL_TARGETS) if args.portals.strip().lower() == 'all' else tuple(
        dict.fromkeys(p.strip().lower() for p in args.portals.split(',') if p.strip()))
    if not args.portals or any(p not in PORTAL_TARGETS for p in args.portals):
        parser.error('Use registered portal names separated by commas')
    tracer = RunTracer('data/agent_runs', print_events=False)
    token = set_active_tracer(tracer)
    tracer.start()
    try:
        public = json.loads(Path(args.profile).read_text())
        private = json.loads(Path(args.private_profile).read_text())
        if not isinstance(public, dict) or not isinstance(private, dict):
            raise ValueError('profile_must_be_an_object')
        profile = CandidateProfile.from_dict(public)
        verify_profile_consistency(profile, private)
        args.query = args.query or (profile.target_roles[0] if profile.target_roles else '')
        if not args.query:
            raise ValueError('target_role_required')
        args.resume_path = args.resume_path or str(resolve_current_resume())
        if not validate_resume_path(args.resume_path)[0]:
            raise ValueError('invalid_resume_file')
        auth_provider = None if args.no_login else AuthProvider(args.auth_config,args.credentials_file)
        with PlaywrightSession(BrowserRuntimeConfig(user_data_dir=args.profile_dir, headless=args.headless)) as runtime:
            report = run_on_page(runtime.page, args, profile, private, JobStore(args.db),auth_provider=auth_provider)
        code = 2 if report['status'] == 'cross_portal_environment_blocked' else 0 if report['preparation']['ready_for_review'] else 4
    except BrowserRuntimeUnavailable as exc:
        report = dict(status='cross_portal_environment_blocked', **exc.diagnostics(), submitted=0, confirmed=0)
        code = 2
    except ProfileFactsConflict as exc:
        report = dict(status='applicant_facts_require_review', fields=list(exc.fields), submitted=0, confirmed=0)
        code = 2
    except AuthProviderUnavailable as exc:
        report = dict(status='auth_configuration_required',reason_code=str(exc),submitted=0,confirmed=0)
        code = 2
    except (OSError, ValueError) as exc:
        report = dict(status='cross_portal_configuration_blocked', reason_code=type(exc).__name__, submitted=0, confirmed=0)
        code = 2
    finally:
        reset_active_tracer(token)
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(report, indent=2, sort_keys=True))
    os.replace(temp, target)
    tracer.finish('completed' if code == 0 else 'acceptance_pending', exit_code=code)
    print(json.dumps({'report': str(target), **report}, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
