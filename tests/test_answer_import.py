import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from answer_import import AnswerImportError,import_reviewed_answers
from answer_facts import format_field_answer, profile_fact_answer
from question_resolver import resolve_application_answer
from agent_backend import main


class AnswerImportTests(unittest.TestCase):
    def run_cli(self,args):
        output=io.StringIO()
        with patch('sys.argv',['agent_backend.py',*args]),patch('scheduled_review.acquire_run_lock',return_value=os.open(self.payload,os.O_RDONLY)),patch('agent_backend.JobStore',side_effect=AssertionError('no DB needed')),patch('agent_backend.os.execv') as launch,redirect_stdout(output):
            code=main()
        return code,json.loads(output.getvalue()),launch.call_count

    def test_missing_import_file_has_specific_reason_and_no_browser(self):
        code,result,launches=self.run_cli(['import-answers','--file',str(self.payload)+'-missing','--private-profile',str(self.profile)])
        self.assertEqual(code,2);self.assertEqual(result['status'],'answer_import_failed')
        self.assertEqual(result['reason_code'],'reviewed_answers_file_missing');self.assertEqual(launches,0)
        self.assertNotIn(self.folder.name,json.dumps(result))

    def test_verify_stops_before_browser_if_required_import_fails(self):
        self.payload.write_text('not JSON; fixture private data')
        code,result,launches=self.run_cli(['verify-linkedin','--reviewed-answers',str(self.payload),'--private-profile',str(self.profile)])
        self.assertEqual(code,2);self.assertEqual(result['reason_code'],'reviewed_answers_file_invalid_json')
        self.assertEqual(launches,0)

    def test_verify_imports_under_worker_lock_before_browser(self):
        code,result,launches=self.run_cli(['verify-linkedin','--reviewed-answers',str(self.payload),'--private-profile',str(self.profile)])
        self.assertEqual(code,0);self.assertEqual(result['status'],'reviewed_answers_imported')
        self.assertEqual(result['added'],1);self.assertEqual(launches,1)
        self.assertEqual(json.loads(self.profile.read_text())['job_answers']['linkedin:9500000001'][self.question],'No')

    def test_missing_private_profile_is_not_reported_as_missing_download(self):
        with self.assertRaises(AnswerImportError) as caught:import_reviewed_answers(str(self.profile)+'-missing',self.payload)
        self.assertEqual(caught.exception.code,'private_profile_missing')

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.profile = Path(self.folder.name) / 'private.json'
        self.payload = Path(self.folder.name) / 'reviewed.json'
        self.profile.write_text(json.dumps(dict(email='fixture@example.invalid', answers={'unrelated':'kept'})))
        self.question = 'Do you hold the fixture certificate?'
        self.rows = [dict(source='linkedin',job_id='9500000001',question=self.question,answer='No')]
        self.write()

    def write(self):
        self.payload.write_text(json.dumps(dict(schema_version=1,answers=self.rows)))

    def test_atomic_private_idempotent_and_job_scoped(self):
        result=import_reviewed_answers(self.profile,self.payload)
        self.assertEqual(result['added'],1); self.assertFalse(result['submission_enabled'])
        data=json.loads(self.profile.read_text())
        self.assertEqual(data['email'],'fixture@example.invalid');self.assertEqual(data['answers'],{'unrelated':'kept'})
        self.assertEqual(self.profile.stat().st_mode&0o777,0o600)
        answer=resolve_application_answer(self.question,{**data,'_application_job':'linkedin:9500000001'},options=['Yes','No'])
        self.assertEqual(answer.answer,'No')
        self.assertNotEqual(resolve_application_answer(self.question,{**data,'_application_job':'linkedin:9500000002'},options=['Yes','No']).status,'RESOLVED')
        timestamp=self.profile.stat().st_mtime_ns
        self.assertEqual(import_reviewed_answers(self.profile,self.payload)['unchanged'],1)
        self.assertEqual(self.profile.stat().st_mtime_ns,timestamp)

    def test_edit_replaces_normalized_duplicate_without_conflict(self):
        import_reviewed_answers(self.profile,self.payload)
        self.rows[0].update(question=self.question.upper(),answer='Yes');self.write()
        self.assertEqual(import_reviewed_answers(self.profile,self.payload)['replaced'],1)
        bank=json.loads(self.profile.read_text())['job_answers']['linkedin:9500000001']
        self.assertEqual(bank,{self.question.upper():'Yes'})

    def test_invalid_second_record_leaves_entire_profile_unchanged(self):
        original=self.profile.read_bytes()
        for row in ({**self.rows[0],'answer':'Yes'}, {**self.rows[0],'job_id':'../../x'},
                    {**self.rows[0],'question':'Enter your password'}, {**self.rows[0],'submission_enabled':True}):
            self.rows=[self.rows[0],row];self.write()
            with self.assertRaises(ValueError):import_reviewed_answers(self.profile,self.payload)
            self.assertEqual(self.profile.read_bytes(),original)

    def test_cli_does_not_initialize_database_policy_or_browser(self):
        output=io.StringIO()
        with patch('sys.argv',['agent_backend.py','import-answers','--file',str(self.payload),'--private-profile',str(self.profile)]),patch('scheduled_review.acquire_run_lock',return_value=os.open(self.payload,os.O_RDONLY)),patch('agent_backend.JobStore',side_effect=AssertionError('no DB')),redirect_stdout(output):
            self.assertEqual(main(),0)
        self.assertNotIn(self.question,output.getvalue());self.assertNotIn('fixture@example.invalid',output.getvalue())

    def test_import_respects_control_decisions_and_keeps_ranges(self):
        self.rows[0]['answer']='10-20';self.write();import_reviewed_answers(self.profile,self.payload)
        profile=json.loads(self.profile.read_text())
        self.assertEqual(profile['job_answers']['linkedin:9500000001'][self.question],'10-20')
        profile.update(_application_job='linkedin:9500000001',_control_answer_bank={self.question:dict(approved=False,answer='')})
        self.assertNotEqual(resolve_application_answer(self.question,profile,options=['Yes','No']).status,'RESOLVED')

    def test_explicit_zero_can_be_formatted_but_missing_or_range_cannot(self):
        self.assertEqual(format_field_answer('Experience','NA - 0','number'),'0')
        self.assertIsNone(format_field_answer('Experience','NA','number'))
        self.assertIsNone(format_field_answer('Client count','10-20','number'))
        self.assertEqual(profile_fact_answer('How many days is your notice period?',{'notice_period_days':'45'}),'45')
