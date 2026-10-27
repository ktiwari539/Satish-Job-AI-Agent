import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,Mock
from zipfile import ZipFile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sheet_control import (parse_control_rows,merge_control_profile,ControlSheetError,control_stop_reason,
                          read_control_workbook,QUESTION_HEADERS,main)
from question_resolver import resolve_application_answer
from auth_bridge import AuthProvider
from application_forms import FormField,build_fill_plan


def fixture_rows(enabled=True):
    config=[['Control'],[],['Setting','Value','Notes'],['agent_enabled',enabled],['operating_mode','VALIDATION'],
            ['experience_years',8],['notice_period_days',30],['current_ctc_inr',1200000],['expected_ctc_inr',1500000]]
    questions=[list(QUESTION_HEADERS),['notice period','Employment','Profile','30 days','YES','LOW',date.today().isoformat(),''],
        ['current CTC','Compensation','Profile','INR 12,00,000 per annum','YES','MEDIUM',date.today().isoformat(),''],
        ['work authorization in India','Authorization','Unresolved','','NO','HIGH',date.today().isoformat(),'']]
    return config,questions


class ControlSheetTests(unittest.TestCase):
    def bundle(self,enabled=True): return parse_control_rows(*fixture_rows(enabled))

    def test_reviewed_answers_reach_resolver_without_mutating_original_profile(self):
        original={'email':'fixture@example.invalid','answers':{}}
        merged=merge_control_profile(original,self.bundle())
        result=resolve_application_answer('Notice period?',merged)
        self.assertEqual(result.answer,'30 days'); self.assertEqual(result.source,'approved_control_question')
        self.assertNotIn('_control_answer_bank',original)

    def test_unknown_india_authorization_blocks_even_an_old_saved_yes(self):
        profile=merge_control_profile({'india_authorized':True,'answers':{'Are you legally authorized to work in India?':'Yes'}},self.bundle())
        result=resolve_application_answer('Are you legally authorized to work in India?',profile,options=('Yes','No'))
        self.assertEqual(result.status,'UNKNOWN_REQUIRED'); self.assertEqual(result.reason,'control_answer_requires_review')

    def test_standard_field_mapping_cannot_bypass_an_unresolved_sheet_decision(self):
        profile=merge_control_profile({'work_authorization':'Yes'},self.bundle())
        field=FormField('work_authorization','Are you legally authorized to work in India?',True)
        plan=build_fill_plan((field,),profile)
        self.assertNotIn('work_authorization',plan.values)
        self.assertEqual(len(plan.unknown_required_fields),1)

    def test_disabled_notice_answer_also_blocks_derived_numeric_answer(self):
        config,questions=fixture_rows();questions[1][4]='NO'
        profile=merge_control_profile({},parse_control_rows(config,questions))
        answer=resolve_application_answer('How many days until you can join?',profile)
        self.assertEqual(answer.status,'UNKNOWN_REQUIRED')

    def test_short_question_pattern_is_not_a_wildcard_for_other_screening_questions(self):
        profile=merge_control_profile({},self.bundle())
        result=resolve_application_answer('Do you have 5 years of insurance experience?',profile,options=('Yes','No'))
        self.assertEqual(result.status,'UNKNOWN_REQUIRED')

    def test_approved_answer_must_match_an_unambiguous_portal_option(self):
        profile=merge_control_profile({},self.bundle())
        self.assertEqual(resolve_application_answer('Notice period',profile,options=('Immediate','90 days')).status,'UNKNOWN_REQUIRED')

    def test_quantity_conflict_reports_only_field_names(self):
        with self.assertRaises(ControlSheetError) as failure:
            merge_control_profile({'experience_years':9,'email':'private@example.invalid'},self.bundle())
        self.assertEqual(failure.exception.fields,('experience_years',))
        self.assertNotIn('private',str(failure.exception))

    def test_local_custom_answer_conflict_is_not_silently_overwritten(self):
        with self.assertRaises(ControlSheetError): merge_control_profile({'answers':{'Notice period':'60 days'}},self.bundle())

    def test_salary_annual_units_are_cross_checked_against_local_lpa(self):
        profile=merge_control_profile({'current_ctc':'12 LPA'},self.bundle())
        self.assertEqual(resolve_application_answer('Current CTC',profile).answer,'INR 12,00,000 per annum')
        with self.assertRaises(ControlSheetError): merge_control_profile({'current_ctc':'15 LPA'},self.bundle())

    def test_conflicting_bank_quantity_is_review_required_and_not_used(self):
        config,questions=fixture_rows();questions[1][3]='60 days'
        bundle=parse_control_rows(config,questions)
        result=resolve_application_answer('Notice period',merge_control_profile({},bundle))
        self.assertEqual(result.status,'UNKNOWN_REQUIRED')

    def test_monthly_salary_is_not_mistaken_for_annual_inr(self):
        config,questions=fixture_rows();questions[2][3]='INR 100000 per month'
        bundle=parse_control_rows(config,questions)
        self.assertFalse(bundle.answers[1]['approved'])

    def test_stale_future_or_unverified_answers_are_not_automated(self):
        for mutate in ('old','future','source'):
            config,questions=fixture_rows()
            if mutate=='old': questions[1][6]=(date.today()-timedelta(days=91)).isoformat()
            elif mutate=='future': questions[1][6]=(date.today()+timedelta(days=2)).isoformat()
            else: questions[1][2]='AI guessed'
            self.assertFalse(parse_control_rows(config,questions).answers[0]['approved'])

    def test_sheet_pause_and_export_snapshot_never_authorize_live_submissions(self):
        self.assertEqual(control_stop_reason(self.bundle(False)),'control_agent_paused')
        self.assertEqual(control_stop_reason(self.bundle(),live_submission=True),'snapshot_cannot_authorize_live_run')
        config,questions=fixture_rows();config[4][1]='LIVE'
        bundle=parse_control_rows(config,questions,source_scope='live_readonly_sheet_bridge')
        self.assertEqual(control_stop_reason(bundle,live_submission=True),'control_high_risk_answers_need_review')

    def test_duplicate_headers_keys_or_password_storage_fail_closed(self):
        config,questions=fixture_rows();config.append(['naukri_password','not-a-real-secret'])
        with self.assertRaisesRegex(ControlSheetError,'private_provider'): parse_control_rows(config,questions)
        config,questions=fixture_rows();questions.append(copy.deepcopy(questions[1]))
        with self.assertRaisesRegex(ControlSheetError,'duplicate_control_question'): parse_control_rows(config,questions)
        config,questions=fixture_rows();config.append(['experience_years',9])
        with self.assertRaisesRegex(ControlSheetError,'duplicate_control_setting'): parse_control_rows(config,questions)
        config,questions=fixture_rows();questions[1][0]='Portal login password'
        with self.assertRaisesRegex(ControlSheetError,'private_provider'): parse_control_rows(config,questions)

    def test_minimal_xlsx_reader_does_not_modify_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.xlsx'
            config,questions=fixture_rows()
            from xml.sax.saxutils import escape
            def xml(rows):
                return '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(
                    '<row r="'+str(i)+'">'+''.join('<c r="'+chr(65+j)+str(i)+'" t="inlineStr"><is><t>'+escape(str(value))+'</t></is></c>' for j,value in enumerate(row))+'</row>' for i,row in enumerate(rows,1))+'</sheetData></worksheet>'
            with ZipFile(path,'w') as archive:
                archive.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Config" r:id="one"/><sheet name="Question_Bank" r:id="two"/></sheets></workbook>')
                archive.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="one" Target="worksheets/sheet1.xml"/><Relationship Id="two" Target="worksheets/sheet2.xml"/></Relationships>')
                archive.writestr('xl/worksheets/sheet1.xml',xml(config));archive.writestr('xl/worksheets/sheet2.xml',xml(questions))
            before=path.read_bytes();bundle=read_control_workbook(path)
            self.assertEqual(bundle.diagnostics()['auto_answer_rows'],2)
            self.assertEqual(path.read_bytes(),before)

    def test_bridge_control_read_uses_dedicated_operation_and_validates_schema(self):
        provider=AuthProvider('/missing/fixture-config')
        provider.config={'fixture':True}
        config,questions=fixture_rows()
        with patch.object(provider,'_request',return_value=dict(schema_version=1,config_rows=config,question_rows=questions)) as call:
            bundle=provider.control_snapshot()
        call.assert_called_once_with('control_snapshot','control')
        self.assertEqual(bundle.source_scope,'live_readonly_sheet_bridge')

    def test_inspection_cli_needs_no_applicant_file_resume_or_browser(self):
        with patch('sheet_control.read_control_workbook',return_value=self.bundle(False)), \
             patch.object(sys,'argv',['sheet_control.py','--control-workbook','fixture.xlsx']),redirect_stdout(io.StringIO()) as output:
            code=main()
        self.assertEqual(code,0);self.assertFalse(json.loads(output.getvalue())['agent_enabled'])

    def test_paused_control_stops_runner_before_browser_or_resume_access(self):
        import certify_portals
        with tempfile.TemporaryDirectory() as directory:
            public=Path(directory)/'public.json';private=Path(directory)/'private.json';report=Path(directory)/'report.json'
            public.write_text(json.dumps(dict(target_roles=['Customer Success Manager'],total_experience_years=8)))
            private.write_text(json.dumps(dict(full_name='Fixture Applicant',email='fixture@example.invalid',phone='2025550123')))
            argv=['certify_portals.py','--profile',str(public),'--private-profile',str(private),
                  '--control-workbook','fixture.xlsx','--report',str(report)]
            with patch.object(sys,'argv',argv),patch('sheet_control.read_control_workbook',return_value=self.bundle(False)), \
                 patch('certify_portals.PlaywrightSession') as runtime,patch('certify_portals.resolve_current_resume') as resume,redirect_stdout(io.StringIO()):
                code=certify_portals.main()
            self.assertEqual(code,4);runtime.assert_not_called();resume.assert_not_called()
            self.assertEqual(json.loads(report.read_text())['status'],'control_agent_paused')

    def test_sheet_company_exclusion_is_enforced_by_shared_eligibility(self):
        from sheet_control import load_requested_control
        from models import CandidateProfile,Job
        from policy import evaluate_eligibility
        config,questions=fixture_rows();config.append(['excluded_companies','Excluded Fixture LLC'])
        provider=Mock();provider.control_snapshot.return_value=parse_control_rows(config,questions)
        public=CandidateProfile.from_dict(dict(total_experience_years=8,india_authorized=True,excluded_companies=['Existing Fixture']))
        updated,_,_=load_requested_control(SimpleNamespace(control_workbook='',use_control_sheet=True),provider,public,{})
        job=Job('linkedin','fixture','Excluded Fixture','Role','India','https://example.invalid','')
        self.assertIn('company_excluded_by_profile',evaluate_eligibility(updated,job).reasons)
        self.assertIn('Existing Fixture',updated.excluded_companies)

    def test_sheet_limits_can_only_tighten_existing_policy_and_reject_fractions(self):
        from sheet_control import restrictive_control_limits
        config,questions=fixture_rows();config.extend([['auto_apply_score',90],['daily_application_cap',5]])
        self.assertEqual(restrictive_control_limits(parse_control_rows(config,questions),80,10),(90,5))
        config[-2][1]=89.9
        with self.assertRaises(ControlSheetError): restrictive_control_limits(parse_control_rows(config,questions),80,10)
