"""Opaque local retry revision; applicant values are never stored in reports."""
import hashlib
import json
from pathlib import Path
from importlib import metadata
from resume_store import _sha256


def preparation_revision(public_profile, private_profile, resume_path):
    payload = {'public': public_profile, 'private': private_profile}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode())
    try:
        digest.update(metadata.version('playwright').encode())
    except metadata.PackageNotFoundError:
        digest.update(b'no-playwright')
    try:
        digest.update(_sha256(Path(resume_path)).encode())
    except OSError:
        digest.update(b'resume-unavailable')
    for name in ('portal_preparation.py', 'question_resolver.py', 'browser_form_runtime.py', 'resume_evidence.py',
                 'review_runner.py', 'profile_consistency.py', 'jd_enrichment.py', 'naukri_readiness.py',
                 'browser_portals.py', 'browser_extractors.py', 'browser_runtime.py', 'application_flow.py',
                 'apply_inspection.py', 'linkedin_application.py', 'linkedin_entry_diagnostics.py',
                 'submission_engine.py', 'release_acceptance.py', 'certify_portals.py'):
        digest.update((Path(__file__).parent / name).read_bytes())
    return digest.hexdigest()
