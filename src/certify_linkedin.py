"""Bounded authenticated-local certification. Never imports a submission runner."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

from agent_trace import RunTracer, set_active_tracer, reset_active_tracer
from easy_apply_debug import debug_easy_apply
from smart_debug_queue import debug_easy_apply_queue, _get_debug_result
from smart_queue_history import record_check

# Historical failures from Issue #3. The confirmed manual job is excluded.
ISSUE3_JOB_IDS = ('4455142560', '4470305150', '4482617347', '4467551783',
                 '4458178908', '4477985661')


def summarize(results):
    by_id = {str(item['job_id']): item for item in results if item.get('job_id')}
    forms = [r for r in by_id.values() if r.get('flow_tested') is True]
    ready = [r for r in forms if r.get('release_checks_passed') is True]
    passed = len(forms) >= 10 and bool(ready)
    return dict(verification_scope='authenticated_local_browser_required',
                acceptance_passed=passed, distinct_jobs_checked=len(by_id),
                distinct_application_forms_exercised=len(forms),
                release_ready_jobs=len(ready), submitted=0, confirmed=0,
                results=list(by_id.values()),
                remaining_gates=[] if passed else [
                    'Ten distinct unapplied LinkedIn forms must be exercised without submitting',
                    'At least one new job must reach Review with identity, resume and Submit control verified'])


def run(args):
    results = []
    urls = list(args.job_url or [])
    if args.include_issue3_jobs:
        urls = ['https://www.linkedin.com/jobs/view/'+jid+'/' for jid in ISSUE3_JOB_IDS] + urls
    common = vars(args).copy()
    common.update(portal='linkedin', debug_easy_apply_only=True, smart_debug=False,
                  smart_debug_queue=False, debug_interactive=False, debug_hold_seconds=0,
                  approve_one_live_application=False, allow_outside_window=False,
                  smart_max_forms=5, max_jobs=20)
    for url in dict.fromkeys(urls):
        local = SimpleNamespace(**{**common, 'job_url': url})
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                debug_easy_apply(local)
            result = _get_debug_result(buffer.getvalue())
        except Exception as exc:
            result = {'status': 'certification_candidate_exception', 'reason_code': type(exc).__name__,
                      'flow_tested': False, 'submitted': 0, 'confirmed': 0}
        from linkedin_exact_job import parse_linkedin_target
        result['job_id'] = parse_linkedin_target(url).job_id
        results.append(result)
        record_check(args.db, result['job_id'], result.get('status', ''), result.get('flow_state', ''),
                     entry_classification=result.get('entry_classification', ''))
        print(json.dumps(result, sort_keys=True), flush=True)
    for _ in range(args.rounds):
        if summarize(results)['acceptance_passed']:
            break
        queue_args = SimpleNamespace(**{**common, 'job_url': '', 'smart_debug': True, 'smart_debug_queue': True})
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            debug_easy_apply_queue(queue_args)
        lines = [json.loads(line) for line in buffer.getvalue().splitlines() if line.startswith('{')]
        queue = next((item for item in reversed(lines) if 'results' in item), {})
        batch = queue.get('results', [])
        results.extend(batch)
        print(json.dumps({'event': 'certification_queue_round', **queue}, sort_keys=True), flush=True)
        if not batch:
            break
    report = summarize(results)
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.tmp')
    temp.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')
    os.replace(temp, target)
    print(json.dumps({'event': 'certification_complete', 'report': str(target),
                      **{k: v for k, v in report.items() if k != 'results'}}, sort_keys=True))
    return 0 if report['acceptance_passed'] else 4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-url', action='append', default=[])
    parser.add_argument('--include-issue3-jobs', action='store_true')
    parser.add_argument('--rounds', type=int, choices=range(0, 5), default=3)
    parser.add_argument('--query', default='Customer Success Manager')
    parser.add_argument('--location', default='India')
    parser.add_argument('--private-profile', default='data/private_profile.json')
    parser.add_argument('--profile-dir', default='browser-profile')
    parser.add_argument('--resume-path', default='')
    parser.add_argument('--db', default='data/jobs.db')
    parser.add_argument('--report', default='data/certification/latest.json')
    parser.add_argument('--headless', action='store_true')
    args = parser.parse_args()
    tracer = RunTracer('data/agent_runs', print_events=False)
    token = set_active_tracer(tracer)
    tracer.start()
    try:
        code = run(args)
        tracer.finish('completed' if code == 0 else 'acceptance_pending', exit_code=code)
        return code
    finally:
        reset_active_tracer(token)


if __name__ == '__main__':
    raise SystemExit(main())
