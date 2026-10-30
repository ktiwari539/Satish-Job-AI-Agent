"""Verified, non-submitting preparation shared by portal adapters."""
from dataclasses import dataclass
from urllib.parse import urlsplit, parse_qs
import re

from application_flow import run_safe_application_flow, _inspect_review
from application_forms import validate_resume_path
from apply_inspection import _looks_like_application_form
from browser_extractors import canonicalize_job_url
from browser_form_runtime import inspect_page_fields
from linkedin_application import run_linkedin_application
from linkedin_applied_status import inspect_exact_applied_status
from linkedin_exact_job import parse_linkedin_target, ensure_exact_target
from naukri_browser_import import valid_naukri_url
from naukri_readiness import job_readiness_flags
from navigation import bounded_goto
from release_acceptance import review_identity_verified
from resume_evidence import inspect_resume_evidence
from submission_engine import _visible_submit_control
from linkedin_entry_diagnostics import classify_linkedin_entry


@dataclass(frozen=True)
class PreparationEvidence:
    state: str
    reason: str = ''
    flow_state: str = 'NOT_RUN'
    form_exercised: bool = False
    exact_job_verified: bool = False
    identity_verified: bool = False
    resume_evidence_state: str = 'not_checked'
    submit_control_verified: bool = False
    unknown_required_count: int = 0
    review_mismatch_count: int = 0
    submission_enabled: bool = False
    submitted: int = 0
    confirmed: int = 0
    entry_classification: str = ''
    entry_state: str = ''


def valid_portal_job_url(job):
    """Permit known public job routes, not arbitrary login/profile URLs."""
    try:
        url = urlsplit(job.url)
        if url.scheme != 'https' or url.username or url.password or url.port not in (None, 443):
            return False
        host = url.hostname or ''
        if job.source == 'linkedin':
            return parse_linkedin_target(job.url).job_id == job.external_id
        if job.source == 'naukri':
            return valid_naukri_url(job.url) and url.path.startswith('/job-listings-')
        if job.source == 'indeed':
            query = parse_qs(url.query, keep_blank_values=True)
            ids = query.get('jk') or query.get('vjk') or []
            return (host == 'indeed.com' or host.endswith('.indeed.com')) and url.path.rstrip('/') in (
                '/viewjob', '/rc/clk', '/pagead/clk', '/jobs') and len(ids) == 1 and ids[0] == job.external_id and not (
                query.get('jk') and query.get('vjk') and query['jk'] != query['vjk'])
        if job.source == 'greenhouse':
            match = re.search(r'/jobs/(\d+)(?:/|$)', url.path)
            ids = parse_qs(url.query).get('gh_jid', [])
            identities = ([match.group(1)] if match else []) + ids
            return host.endswith(('.greenhouse.io', '.greenhouse.com')) and bool(identities) and all(
                value == job.external_id for value in identities)
        if job.source == 'lever':
            parts = url.path.strip('/').split('/')
            return host in ('jobs.lever.co', 'jobs.eu.lever.co') and len(parts) in (2, 3) and parts[1] == job.external_id and (
                len(parts) == 2 or parts[2] == 'apply')
    except (ValueError, TypeError, AttributeError):
        pass
    return False


def exact_job_page(page, job):
    if not valid_portal_job_url(job):return False
    if job.source == 'linkedin':
        try:
            ensure_exact_target(page,parse_linkedin_target(job.url))
            return True
        except ValueError:
            return False
    return canonicalize_job_url(str(page.url)) == canonicalize_job_url(job.url)


def prepare_portal_job(page, job, profile, *, resume_path, applicant_experience_years=0):
    """Fill verified fields and advance known forms; final Submit is inspected only.

    Native Naukri/Indeed one-click Apply buttons are deliberately not treated
    as navigation. A verified visible application form is required first.
    """
    if not validate_resume_path(resume_path)[0]:
        return PreparationEvidence('BLOCKED', 'invalid_resume_file')
    if not valid_portal_job_url(job):
        return PreparationEvidence('BLOCKED', 'unsupported_or_ambiguous_job_url')
    if job.source == 'naukri':
        flags, _ = job_readiness_flags(job.title, job.company, job.url, job.description, applicant_experience_years)
        if flags:
            return PreparationEvidence('BLOCKED', flags[0])
    bounded_goto(page, job.url)
    if not exact_job_page(page, job):
        return PreparationEvidence('BLOCKED', 'job_page_or_authentication_redirect')
    if job.source == 'linkedin':
        status = inspect_exact_applied_status(page, parse_linkedin_target(job.url))
        if status['status'] == 'linkedin_exact_job_applied_visible':
            return PreparationEvidence('BLOCKED', 'already_applied_on_portal', exact_job_verified=True)
        if status['status'] == 'application_status_ambiguous':
            return PreparationEvidence('BLOCKED', 'applied_status_requires_review', exact_job_verified=True)
        run = run_linkedin_application(page, profile, open_easy_apply=True,
            open_external_apply=False, fill_application=True, advance_application=True,
            inspect_review=True, live_submission_enabled=False, submit_application=False,
            resume_path=resume_path)
        flow = run.flow
        if flow is None:
            entry=classify_linkedin_entry(page,job.url,entry=run.entry)
            classification=entry['entry_classification']
            return PreparationEvidence('BLOCKED','linkedin_'+classification.lower(),exact_job_verified=True,
                entry_classification=classification,entry_state=run.entry.application_state)
    else:
        fields = inspect_page_fields(page)
        try:
            single_form = page.evaluate("""() => {
              const visible = el => { const r=el.getBoundingClientRect(), s=getComputedStyle(el);
                return r.width>0 && r.height>0 && s.display!=='none' && s.visibility!=='hidden'; };
              const forms = [...document.querySelectorAll('form')].filter(visible);
              if (forms.length !== 1) return false;
              return !!forms[0].querySelector('input[type="file"]') ||
                [...forms[0].querySelectorAll('h1,h2,h3,legend')].some(el => /application|apply for/i.test(el.innerText));
            }""") is True
        except Exception:
            single_form = False
        if not single_form or not _looks_like_application_form(fields):
            return PreparationEvidence('BLOCKED', 'application_entry_requires_portal_adapter', exact_job_verified=True)
        flow = run_safe_application_flow(page, profile, resume_path=resume_path,
            advance=True, inspect_review=True, live_submission_enabled=False,
            application_type='EXTERNAL_APPLY')
    exact = exact_job_page(page, job)
    checks, mismatches = _inspect_review(page, profile)
    identity = review_identity_verified(profile, checks)
    resume = inspect_resume_evidence(page, resume_path, external=job.source != 'linkedin')
    submit, _ = _visible_submit_control(page, 'LINKEDIN_EASY_APPLY' if job.source == 'linkedin' else 'EXTERNAL_APPLY')
    ready = (flow.state in ('REVIEW_INSPECTED', 'SUBMIT_READY') and exact and identity and
             not mismatches and resume == 'matching_resume_selected' and submit is not None and
             not flow.unknown_required_fields and not flow.missing_profile_values)
    return PreparationEvidence(
        state='READY_FOR_REVIEW' if ready else 'BLOCKED',
        reason='' if ready else flow.state if flow.state not in ('REVIEW_INSPECTED', 'SUBMIT_READY') else 'review_cross_checks_incomplete',
        flow_state=flow.state, form_exercised=True, exact_job_verified=exact,
        identity_verified=identity, resume_evidence_state=resume,
        submit_control_verified=submit is not None,
        unknown_required_count=len(flow.unknown_required_fields), review_mismatch_count=len(mismatches))
