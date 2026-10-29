"""Real loopback HTTP tests; no browser, Google bridge or portal access."""
from dataclasses import asdict
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from agent_backend import make_server,load_local_token,linkedin_verification_command
from application_queue import ApplicationQueue,QueueError
from automation_policy import load_automation_policy
from store import JobStore
from test_application_queue import job,REVISION


class AgentBackendTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.queue=ApplicationQueue(JobStore(str(Path(self.folder.name)/'jobs.db')))
        self.policy=load_automation_policy(str(ROOT/'config/automation_policy.production.json'))
        self.token='synthetic_backend_token_'+'a'*32
        self.server=make_server(self.queue,self.policy,self.token,port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)

    def request(self,method,path,payload=None,headers=None,authenticated=True):
        headers={**({'Authorization':'Bearer '+self.token} if authenticated else {}),**(headers or {})}
        raw=json.dumps(payload) if payload is not None else None
        if raw is not None: headers.setdefault('Content-Type','application/json')
        client=HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            client.request(method,path,body=raw,headers=headers)
            response=client.getresponse();body=json.loads(response.read())
            return response.status,body,dict(response.getheaders())
        finally: client.close()

    def test_only_health_is_public_and_private_responses_are_not_cached(self):
        code,body,_=self.request('GET','/health',authenticated=False)
        self.assertEqual((code,body),(200,dict(status='ok',submission_enabled=False)))
        self.assertEqual(self.request('GET','/v1/status',authenticated=False)[0],401)
        code,body,headers=self.request('GET','/v1/status')
        self.assertEqual(code,200);self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertFalse(body['submission_enabled']);self.assertFalse(body['application_ready'])
        self.assertNotIn(self.token,json.dumps(body))

    def test_cross_origin_and_untrusted_host_requests_cannot_mutate_queue(self):
        for headers in ({'Origin':'https://evil.invalid'},{'Host':'evil.invalid'}, {'Authorization':'Bearer wrong'}):
            self.assertIn(self.request('POST','/v1/queue/pause',{},headers=headers)[0],(401,403))
            self.assertFalse(self.queue.paused())

    def test_pause_resume_and_job_discovery_are_operable_without_submission_endpoints(self):
        payload=dict(jobs=[asdict(job())],facts_revision=REVISION)
        self.assertEqual(self.request('POST','/v1/jobs',payload)[0],200)
        self.assertEqual(self.request('POST','/v1/jobs',payload)[0],200)
        self.assertEqual(len(self.queue.snapshot()['jobs']),1)
        self.assertTrue(self.request('POST','/v1/queue/pause',{})[1]['paused'])
        self.assertIsNone(self.queue.claim(sources=('linkedin',)))
        self.assertFalse(self.request('POST','/v1/queue/resume',{})[1]['paused'])
        for path in ('/v1/submit','/v1/jobs/1/confirmed','/v1/jobs/1/prepared'):
            self.assertEqual(self.request('POST',path,{})[0],404)
        self.assertEqual(self.queue.snapshot()['counts']['CONFIRMED'],0)

    def test_bad_inputs_are_bounded_and_do_not_echo_private_body_values(self):
        body=dict(jobs=[{**asdict(job()),'email':'private@example.invalid'}],facts_revision=REVISION)
        code,result,_=self.request('POST','/v1/jobs',body)
        self.assertEqual(code,400);self.assertNotIn('private@example.invalid',json.dumps(result))
        for query in ('limit=100000','limit=1&limit=2','state=CONFIRMED&extra=secret','limit=abc'):
            self.assertEqual(self.request('GET','/v1/jobs?'+query)[0],400)
        self.assertEqual(self.queue.snapshot()['jobs'],[])

    def test_private_local_token_creation_reuse_and_permission_checks(self):
        path=Path(self.folder.name)/'token'
        token=load_local_token(path)
        self.assertEqual(token,load_local_token(path))
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        os.chmod(path,0o644)
        with self.assertRaises(QueueError): load_local_token(path)
        alias=Path(self.folder.name)/'symlink';alias.symlink_to(path)
        with self.assertRaises(QueueError): load_local_token(alias)
        with self.assertRaisesRegex(QueueError,'loopback'): make_server(self.queue,self.policy,self.token,host='0.0.0.0',port=0)

    def test_manual_acceptance_routes_to_linkedin_with_current_controls_and_no_login_or_submit(self):
        args=SimpleNamespace(max_jobs=10,db='data/jobs.db',profile='public.json',private_profile='private.json',
            profile_dir='existing profile',control_workbook='',auth_config='existing bridge.json',query='CSM; $(literal)',location='India')
        command=linkedin_verification_command(args,python='existing-python')
        self.assertEqual(command[0],'existing-python')
        self.assertIn('--use-control-sheet',command)
        self.assertEqual(command[command.index('--portals')+1],'linkedin')
        self.assertEqual(command[command.index('--otp-mode')+1],'none')
        self.assertIn('--no-login',command)
        self.assertFalse(any('approve' in value or 'submit' in value for value in command))
        self.assertIn(args.query,command)
        args.control_workbook='fresh snapshot.xlsx'
        snapshot=linkedin_verification_command(args)
        self.assertIn('--control-workbook',snapshot);self.assertNotIn('--use-control-sheet',snapshot)


if __name__=='__main__': unittest.main()
