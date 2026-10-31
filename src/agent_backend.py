"""Local backend API and CLI for durable review work. No application clicks."""
import argparse
from dataclasses import fields
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import stat
import re
from urllib.parse import parse_qs, urlsplit

from application_queue import ApplicationQueue, QueueError
from automation_policy import load_automation_policy
from models import Job
from store import JobStore


MAX_BODY = 65536


def linkedin_verification_command(args, *, python=None):
    """One manual acceptance run; fixed LinkedIn scope, no login or submission."""
    root = Path(__file__).resolve().parents[1]
    import sys
    command = [python or sys.executable, str(root/'src/certify_portals.py'), '--portals', 'linkedin',
        '--max-jobs', str(args.max_jobs), '--no-login', '--otp-mode', 'none',
        '--db', args.db, '--profile', args.profile, '--private-profile', args.private_profile,
        '--profile-dir', args.profile_dir, '--report', 'data/certification/backend-linkedin.json',
        '--location', args.location]
    if args.control_workbook:
        command.extend(['--control-workbook', args.control_workbook])
    else:
        command.extend(['--use-control-sheet', '--auth-config', args.auth_config])
    if args.query: command.extend(['--query',args.query])
    return command


def load_local_token(path):
    """Create a private random local API token; never print it or reuse passwords."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise QueueError('backend_token_file_requires_private_permissions') from None
    else:
        with os.fdopen(fd, 'w') as output:
            output.write(secrets.token_urlsafe(32)+'\n')
    if target.stat().st_size > 1024: raise QueueError('backend_token_invalid')
    token = target.read_text().strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{40,128}',token):
        raise QueueError('backend_token_invalid')
    return token


def import_jobs(queue, payload):
    if not isinstance(payload, dict) or set(payload) != {'jobs', 'facts_revision'} or not isinstance(payload['jobs'], list) or not 1 <= len(payload['jobs']) <= 20:
        raise QueueError('invalid_job_import')
    allowed = {item.name for item in fields(Job)}
    jobs = []
    from application_queue import canonical_queue_job
    for item in payload['jobs']:
        if not isinstance(item, dict) or set(item)-allowed: raise QueueError('invalid_queue_job')
        try: jobs.append(canonical_queue_job(Job(**item)))
        except TypeError: raise QueueError('invalid_queue_job') from None
    # All shapes are validated before any row is changed. Individual identities
    # remain idempotent; import is discovery, never qualification/approval.
    return queue.enqueue_many(jobs, payload['facts_revision'])


def backend_status(queue, policy):
    result = queue.snapshot()
    result['capacity'] = queue.store.submission_budget(policy)
    result['capacity_scope'] = 'local_policy_before_live_sheet_restrictions'
    result['worker_requires_current_controls'] = True
    result['application_ready'] = False
    return result


def make_server(queue, policy, token, *, host='127.0.0.1', port=8765):
    if host != '127.0.0.1': raise QueueError('backend_requires_loopback')
    if not isinstance(token, str) or len(token) < 40: raise QueueError('backend_token_invalid')

    class Handler(BaseHTTPRequestHandler):
        # Request URLs and credentials must never enter default access logs.
        def log_message(self, *_): pass

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def send_json(self, status, result):
            data = json.dumps(result, sort_keys=True).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            hosts = ('127.0.0.1:'+str(self.server.server_port), 'localhost:'+str(self.server.server_port))
            if self.headers.get('Host') not in hosts or self.headers.get('Origin') is not None:
                self.send_json(403, dict(error='backend_local_client_required'))
                return False
            supplied = self.headers.get('Authorization', '')
            if not hmac.compare_digest(supplied.encode('utf-8'), ('Bearer '+token).encode('utf-8')):
                self.send_json(401, dict(error='backend_authentication_required'))
                return False
            return True

        def do_GET(self):
            target = urlsplit(self.path)
            if target.path == '/health' and not target.query:
                self.send_json(200, dict(status='ok', submission_enabled=False))
                return
            if not self.authorized(): return
            try:
                if target.path == '/v1/status' and not target.query:
                    self.send_json(200, backend_status(queue, policy))
                elif target.path == '/v1/jobs':
                    query = parse_qs(target.query, keep_blank_values=True)
                    if set(query)-{'limit', 'state'} or any(len(values)!=1 for values in query.values()):
                        raise QueueError('invalid_queue_query')
                    self.send_json(200, queue.snapshot(limit=int(query.get('limit', ['50'])[0]), state=query.get('state', [None])[0]))
                else: self.send_json(404, dict(error='backend_route_not_found'))
            except ValueError as exc:
                self.send_json(400, dict(error=str(exc) if isinstance(exc, QueueError) else 'invalid_queue_query'))
            except Exception:
                self.send_json(503, dict(error='backend_storage_unavailable'))

        def do_POST(self):
            if not self.authorized(): return
            target = urlsplit(self.path)
            if target.query or target.path not in ('/v1/queue/pause', '/v1/queue/resume', '/v1/jobs'):
                self.send_json(404, dict(error='backend_route_not_found'))
                return
            try:
                if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/json':
                    raise QueueError('backend_json_body_required')
                lengths = self.headers.get_all('Content-Length', [])
                if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= MAX_BODY:
                    raise QueueError('backend_body_size_invalid')
                raw = self.rfile.read(int(lengths[0]))
                if len(raw) != int(lengths[0]): raise QueueError('backend_incomplete_request')
                payload = json.loads(raw)
                if target.path == '/v1/jobs':
                    ids = import_jobs(queue, payload)
                    self.send_json(200, dict(queued_ids=ids, submission_enabled=False))
                else:
                    if payload != {}: raise QueueError('invalid_pause_request')
                    queue.set_paused(target.path.endswith('/pause'))
                    self.send_json(200, dict(paused=queue.paused(), submission_enabled=False))
            except (ValueError, UnicodeError) as exc:
                self.send_json(400, dict(error=str(exc) if isinstance(exc, QueueError) else 'backend_json_invalid'))
            except Exception:
                self.send_json(503, dict(error='backend_storage_unavailable'))

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='data/jobs.db')
    parser.add_argument('--policy', default='config/automation_policy.production.json')
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('status', 'pause', 'resume'): sub.add_parser(name)
    serve = sub.add_parser('serve')
    serve.add_argument('--port', type=int, default=8765)
    serve.add_argument('--token-file', default='data/backend/token')
    questions=sub.add_parser('review-questions',help='Review actual unanswered prompts privately; no browser or submission')
    questions.add_argument('--private-profile',default='data/private_profile.json')
    questions.add_argument('--questions-file',default='data/questions/pending.json')
    answers=sub.add_parser('import-answers',help='Import explicitly reviewed private job answers; no browser or submission')
    answers.add_argument('--file',required=True)
    answers.add_argument('--private-profile',default='data/private_profile.json')
    verify = sub.add_parser('verify-linkedin',help='Manual non-submitting acceptance using the existing Mac session')
    verify.add_argument('--max-jobs',type=int,choices=range(1,21),default=10)
    verify.add_argument('--profile',default='config/qa_profile.json')
    verify.add_argument('--private-profile',default='data/private_profile.json')
    verify.add_argument('--profile-dir',default='browser-profile')
    verify.add_argument('--auth-config',default='data/auth_bridge.json')
    verify.add_argument('--control-workbook',default='')
    verify.add_argument('--query',default='')
    verify.add_argument('--location',default='India')
    args = parser.parse_args()
    try:
        if args.action in ('review-questions', 'import-answers'):
            from question_requests import review_pending_questions
            from answer_import import import_reviewed_answers
            from scheduled_review import acquire_run_lock
            descriptor=acquire_run_lock('data/review-worker.lock')
            if descriptor is None:
                print(json.dumps(dict(status='review_worker_already_running',submission_enabled=False)))
                return 4
            try:
                if args.action == 'import-answers':
                    result=import_reviewed_answers(args.private_profile,args.file)
                    status='reviewed_answers_imported'
                else:
                    result=review_pending_questions(args.private_profile,path=args.questions_file)
                    status='questions_reviewed'
                print(json.dumps(dict(status=status,**result)))
                return 0
            finally:os.close(descriptor)
        store = JobStore(args.db)
        Path(args.db).chmod(0o600)
        queue = ApplicationQueue(store)
        policy = load_automation_policy(args.policy)
        if args.action == 'verify-linkedin':
            from scheduled_review import acquire_run_lock
            descriptor=acquire_run_lock('data/review-worker.lock')
            if descriptor is None:
                print(json.dumps(dict(status='review_worker_already_running',submission_enabled=False)))
                return 4
            command=linkedin_verification_command(args)
            try: os.execv(command[0],command)
            finally: os.close(descriptor)
        if args.action in ('pause', 'resume'): queue.set_paused(args.action=='pause')
        if args.action != 'serve':
            print(json.dumps(backend_status(queue, policy), sort_keys=True))
            return 0
        if not 1 <= args.port <= 65535: raise QueueError('backend_port_invalid')
        token = load_local_token(args.token_file)
        server = make_server(queue, policy, token, port=args.port)
        print(json.dumps(dict(status='backend_listening', host='127.0.0.1', port=server.server_port,
                              submission_enabled=False)), flush=True)
        try: server.serve_forever()
        except KeyboardInterrupt: pass
        finally: server.server_close()
        return 0
    except (OSError, ValueError):
        print(json.dumps(dict(status='backend_configuration_required', submission_enabled=False)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
