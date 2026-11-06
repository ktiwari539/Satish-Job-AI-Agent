"""Revalidate inputs immediately before the existing approved submit action."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from agent_trace import trace_event
from automation_policy import load_automation_policy
from matcher import score_profile
from models import CandidateProfile
from policy import evaluate_eligibility
from preparation_revision import preparation_revision
from resume_facts import derive_resume_facts
from sheet_control import load_requested_control, control_stop_reason, restrictive_control_limits


def current_submission_guard(job, *, args, store, provider, testing_mode,
                             profile, private_profile, policy):
    """Return a fail-closed guard; the caller still needs its job approval gate.

    Compare the actual local source bytes and resume as well as a fresh
    control overlay. Never carry answers/credentials into a reservation row.
    """
    paths = [Path(args.profile), Path(args.private_profile), Path(args.resume_path)]
    import hashlib
    def source_revision():
        digest = hashlib.sha256()
        for path in paths: digest.update(hashlib.sha256(path.read_bytes()).digest())
        return digest.hexdigest()
    baseline_sources = source_revision()
    baseline_facts = preparation_revision(asdict(profile), private_profile, args.resume_path)

    def guard():
        try:
            if source_revision() != baseline_sources:
                trace_event('submission_guard_blocked',reason='applicant_sources_changed')
                return False
            raw_public=json.loads(Path(args.profile).read_text())
            raw_private=json.loads(Path(args.private_profile).read_text())
            if not isinstance(raw_public,dict) or not isinstance(raw_private,dict): return False
            current_profile,current_private,control = load_requested_control(args,provider,
                CandidateProfile.from_dict(raw_public),raw_private)
            for key,value in derive_resume_facts(args.resume_path).items():
                if current_private.get(key) in (None,'') and value not in (None,''):
                    current_private[key]=value
            if control_stop_reason(control,live_submission=not testing_mode):
                trace_event('submission_guard_blocked',reason='current_controls_block_submission')
                return False
            if preparation_revision(asdict(current_profile),current_private,args.resume_path) != baseline_facts:
                trace_event('submission_guard_blocked',reason='reviewed_facts_changed')
                return False
            current_policy = load_automation_policy(args.policy)
            threshold = max(policy.threshold,current_policy.threshold)
            cap = min(policy.daily_success_cap,current_policy.daily_success_cap)
            if control is not None: threshold,cap = restrictive_control_limits(control,threshold,cap)
            current_policy = replace(current_policy,threshold=threshold,daily_success_cap=cap)
            if (not current_policy.live_submission_enabled or score_profile(current_profile,job,threshold).decision != 'APPLY'
                    or not evaluate_eligibility(current_profile,job).eligible):
                return False
            return store.reserve_submission_attempt(job,policy=current_policy,
                allow_outside_window=testing_mode or args.allow_outside_window)
        except (OSError,ValueError,RuntimeError,TypeError,AttributeError):
            trace_event('submission_guard_blocked',reason='current_inputs_unavailable')
            return False
    return guard
