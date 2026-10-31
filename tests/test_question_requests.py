from contextlib import redirect_stdout
import io,json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from browser_form_runtime import BrowserFieldSnapshot
from question_requests import record_pending_questions,review_pending_questions
from question_resolver import resolve_application_answer


class QuestionRequests(unittest.TestCase):
    def test_legacy_native_on_option_does_not_reject_reviewed_yes(self):
        field=BrowserFieldSnapshot('fixture','Do you hold the fixture certificate?',True,'radio',('on',))
        self.capture((field,),(field.label,))
        payload=json.loads(self.path.read_text());rows=payload['questions']
        # Also exercise an older capture still containing the broken options.
        for row in rows:row['options']=['on']
        self.path.write_text(json.dumps(payload))
        with patch('builtins.input',return_value='Yes'),redirect_stdout(io.StringIO()):
            self.assertEqual(review_pending_questions(self.profile,path=self.path)['answers_saved'],1)
        saved=json.loads(self.profile.read_text())
        self.assertEqual(resolve_application_answer(field.label,{**saved,'_application_job':'linkedin:9400000001'},options=['Yes','No']).answer,'Yes')

    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'pending.json';self.profile=Path(self.folder.name)/'private.json'
        self.profile.write_text(json.dumps(dict(email='fixture@example.invalid',answers={})))
        self.job=SimpleNamespace(source='linkedin',external_id='9400000001')

    def capture(self,fields,unknown,profile=None):
        with patch('question_requests.inspect_page_fields',return_value=fields),patch('question_requests.inspect_screening_groups',return_value=()):
            return record_pending_questions(None,self.job,profile or {},unknown,path=self.path)

    def test_actual_prompts_are_private_idempotent_and_contain_no_answer_values(self):
        field=BrowserFieldSnapshot('certificate','Do you hold the employer certificate?',True,'radio',('Yes','No'))
        for _ in range(2):self.capture((field,),(field.label,),dict(answers={'unrelated':'private-answer'}))
        data=json.loads(self.path.read_text())
        self.assertEqual(len(data['questions']),1)
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertNotIn('private-answer',self.path.read_text())
        self.assertNotIn('answer',data['questions'][0])

    def test_credential_and_resume_fields_are_never_collected(self):
        fields=tuple(BrowserFieldSnapshot(str(i),q,True,t) for i,(q,t) in enumerate((
            ('Enter your OTP code','text'),('Your password','password'),('private-resume.pdf','radio'),('fixture@example.invalid','text'))))
        self.assertEqual(self.capture(fields,tuple(f.label for f in fields)),'')
        self.assertFalse(self.path.exists())

    def test_review_once_reuses_verified_answer_and_allows_an_explicit_edit(self):
        field=BrowserFieldSnapshot('certificate','Do you hold the employer certificate?',True,'radio',('Yes','No'))
        self.capture((field,),(field.label,))
        with patch('builtins.input',return_value='No'),redirect_stdout(io.StringIO()):
            self.assertEqual(review_pending_questions(self.profile,path=self.path)['answers_saved'],1)
        profile=json.loads(self.profile.read_text())
        self.assertEqual(resolve_application_answer(field.label,{**profile,'_application_job':'linkedin:9400000001'},options=field.options).answer,'No')
        self.assertNotEqual(resolve_application_answer(field.label,{**profile,'_application_job':'linkedin:9400000002'},options=field.options).status,'RESOLVED')
        self.assertEqual(profile['email'],'fixture@example.invalid')
        self.assertEqual(self.profile.stat().st_mode&0o777,0o600)
        self.capture((field,),(field.label,))
        with patch('builtins.input',return_value='Yes'),redirect_stdout(io.StringIO()):review_pending_questions(self.profile,path=self.path)
        self.assertEqual(resolve_application_answer(field.label,{**json.loads(self.profile.read_text()),'_application_job':'linkedin:9400000001'},options=field.options).answer,'Yes')
        self.assertNotIn('"answer":',self.path.read_text())

    def test_invalid_option_or_skip_cannot_create_an_answer(self):
        field=BrowserFieldSnapshot('certificate','Do you hold the employer certificate?',True,'radio',('Yes','No'))
        self.capture((field,),(field.label,))
        for value in ('','maybe'):
            with patch('builtins.input',return_value=value),redirect_stdout(io.StringIO()):
                self.assertEqual(review_pending_questions(self.profile,path=self.path)['answers_saved'],0)
        self.assertEqual(json.loads(self.profile.read_text())['answers'],{})

    def test_control_review_is_never_overridden_with_a_private_answer(self):
        field=BrowserFieldSnapshot('a','Current CTC (LPA)',True,'number')
        self.capture((field,),(field.label,),{'_control_answer_bank':{'current ctc':dict(approved=False,answer='')}})
        with patch('builtins.input',side_effect=AssertionError('must review in Sheet')),redirect_stdout(io.StringIO()):
            self.assertEqual(review_pending_questions(self.profile,path=self.path)['answers_saved'],0)

    def test_approved_control_value_rejected_by_field_format_still_requires_sheet_review(self):
        field=BrowserFieldSnapshot('a','Current CTC',True,'number')
        profile={'_control_answer_bank':{'current ctc':dict(approved=True,answer='12.5 LPA')}}
        self.capture((field,),(field.label,),profile)
        with patch('builtins.input',side_effect=AssertionError('control format requires Sheet review')),redirect_stdout(io.StringIO()):
            self.assertEqual(review_pending_questions(self.profile,path=self.path)['answers_saved'],0)

    def test_edit_of_a_shared_contact_fact_updates_the_verified_profile(self):
        field=BrowserFieldSnapshot('email','Email',True,'email')
        self.capture((field,),(field.label,))
        with patch('builtins.input',return_value='updated@example.invalid'),redirect_stdout(io.StringIO()):
            review_pending_questions(self.profile,path=self.path)
        profile=json.loads(self.profile.read_text())
        self.assertEqual(profile['email'],'updated@example.invalid')
        from application_forms import FormField,build_fill_plan
        self.assertEqual(build_fill_plan((FormField('email','Email',True,'email'),),profile).values['email'],'updated@example.invalid')


if __name__=='__main__':unittest.main()
