"""Last-click source/control checks with local synthetic files only."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from automation_policy import load_automation_policy
from current_submission_guard import current_submission_guard
from sheet_control import load_requested_control,parse_control_rows
from store import JobStore
from test_application_queue import job
from test_durable_review import PROFILE
import test_sheet_control as sheet_fixtures


class CurrentSubmissionGuardTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        root=Path(self.folder.name)
        self.args=SimpleNamespace(profile=str(root/'public.json'),private_profile=str(root/'private.json'),
            resume_path=str(root/'resume.pdf'),policy=str(root/'policy.json'),
            use_control_sheet=False,control_workbook='',allow_outside_window=True)
        self.private=dict(full_name='Fixture Applicant',email='fixture@example.invalid',phone='2025550123')
        Path(self.args.profile).write_text(json.dumps(asdict(PROFILE)))
        Path(self.args.private_profile).write_text(json.dumps(self.private))
        Path(self.args.resume_path).write_bytes(b'%PDF-1.4 synthetic fixture')
        Path(self.args.policy).write_bytes((ROOT/'config/automation_policy.production.json').read_bytes())
        self.policy=load_automation_policy(self.args.policy)
        self.store=JobStore(str(root/'jobs.db'))

    def guard(self,profile=PROFILE,private=None,provider=None):
        return current_submission_guard(job(),args=self.args,store=self.store,provider=provider,
            testing_mode=True,profile=profile,private_profile=private or self.private,policy=self.policy)

    def test_unchanged_verified_inputs_can_reserve_only_once(self):
        guard=self.guard()
        self.assertTrue(guard());self.assertFalse(guard())
        self.assertTrue(self.store.has_submission_attempt(job()))
        self.assertIsNone(self.store.get_confirmed_submission(job().source,job().external_id))

    def test_source_or_resume_changes_during_preparation_block_reservation(self):
        for field in ('profile','private_profile','resume_path'):
            path=Path(getattr(self.args,field));before=path.read_bytes();guard=self.guard()
            path.write_bytes(before+b' ')
            self.assertFalse(guard(),field)
            self.assertFalse(self.store.has_submission_attempt(job()))
            path.write_bytes(before)

    def test_data_changed_before_guard_creation_cannot_match_stale_in_memory_facts(self):
        Path(self.args.private_profile).write_text(json.dumps({**self.private,'email':'different@example.invalid'}))
        self.assertFalse(self.guard()())
        self.assertFalse(self.store.has_submission_attempt(job()))

    def test_new_policy_disabled_blocks_old_preparation(self):
        document=json.loads(Path(self.args.policy).read_text())
        guard=self.guard();document['application']['live_submission_enabled']=False
        Path(self.args.policy).write_text(json.dumps(document))
        self.assertFalse(guard())
        self.assertFalse(self.store.has_submission_attempt(job()))

    def test_fresh_sheet_pause_and_connection_failure_block_reservation(self):
        config,questions=sheet_fixtures.ControlSheetTests().authorized_rows()
        provider=Mock();provider.control_snapshot.return_value=parse_control_rows(config,questions)
        self.args.use_control_sheet=True
        public,private,_=load_requested_control(self.args,provider,PROFILE,self.private)
        guard=self.guard(profile=public,private=private,provider=provider)
        config[3][1]=False;provider.control_snapshot.return_value=parse_control_rows(config,questions)
        self.assertFalse(guard())
        provider.control_snapshot.side_effect=RuntimeError('private bridge response')
        self.assertFalse(guard())
        self.assertFalse(self.store.has_submission_attempt(job()))


if __name__=='__main__': unittest.main()
