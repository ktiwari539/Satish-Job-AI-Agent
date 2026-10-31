import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from application_forms import FormField,build_fill_plan
from question_resolver import resolve_application_answer
from sheet_control import resolve_control_answer


class AnswerFactFormats(unittest.TestCase):
    def test_salary_variants_use_explicit_units_and_keep_current_expected_distinct(self):
        profile=dict(current_ctc_inr='1250000',expected_ctc_inr='1900000')
        fields=(FormField('a','Please specify your present annual compensation in LPA *',True,'number'),
                FormField('b','What are your salary expectations in INR?',True,'number'))
        plan=build_fill_plan(fields,profile)
        self.assertEqual(plan.values,dict(a='12.5',b='1900000'))
        self.assertFalse(plan.unknown_required_fields)

    def test_exact_saved_units_are_converted_without_changing_the_fact(self):
        fields=(FormField('a','Current CTC (INR)',True,'number'),)
        plan=build_fill_plan(fields,dict(answers={'Current CTC (INR)':'12.5 LPA'}))
        self.assertEqual(plan.values,dict(a='1250000'))

    def test_machine_key_cannot_override_visible_lpa_units(self):
        field=FormField('currentSalary.amount','Current CTC (LPA)',True,'number')
        self.assertEqual(build_fill_plan((field,),dict(current_ctc_inr='1250000')).values[field.key],'12.5')

    def test_unknown_units_and_foreign_or_monthly_salary_are_not_assumed(self):
        for question in ('Current CTC (USD)','Current monthly salary','Current fixed salary','Current and expected CTC'):
            with self.subTest(question=question):
                result=resolve_application_answer(question,dict(current_ctc_inr='1250000'))
                self.assertNotEqual(result.status,'RESOLVED')
        plan=build_fill_plan((FormField('a','Current CTC',True,'number'),),dict(current_ctc='12.5 LPA'))
        self.assertEqual(plan.values,{})
        self.assertTrue(plan.unknown_required_fields)

    def test_industry_and_lower_bound_years_never_become_exact_role_tenure(self):
        for question in ('How many years of insurance experience do you have?',
                         'How many years of work experience do you have with Salesforce?'):
            self.assertNotEqual(resolve_application_answer(question,dict(experience_years='8')).status,'RESOLVED')
        self.assertNotEqual(resolve_application_answer('Customer success experience (years)',dict(customer_success_years='7+')).status,'RESOLVED')

    def test_verified_notice_and_role_years_cover_common_wording(self):
        fields=(FormField('a','Please specify your notice period in days',True,'number'),
                FormField('b','Customer success experience (years)',True,'number'))
        self.assertEqual(build_fill_plan(fields,dict(notice_period='30 days',customer_success_years='7')).values,dict(a='30',b='7'))
        self.assertNotEqual(resolve_application_answer('Notice period in days',dict(notice_period='1 month')).status,'RESOLVED')

    def test_options_keep_the_original_observed_label(self):
        field=FormField('a','Current CTC (LPA)',True,'select-one',('Select','12.5 LPA','20 LPA'))
        self.assertEqual(build_fill_plan((field,),dict(current_ctc_inr='1250000')).values['a'],'12.5 LPA')

    def test_control_decision_reuses_units_and_blocked_scope_cannot_be_bypassed(self):
        profile={'_control_answer_bank':{'current ctc':dict(approved=True,answer='12.5 LPA')}}
        self.assertEqual(resolve_control_answer('Present annual compensation in INR',profile,(),True)['answer'],'1250000')
        profile['_control_answer_bank']['current ctc']['approved']=False
        profile['current_ctc_inr']='1250000'
        self.assertNotEqual(resolve_application_answer('Current CTC (LPA)',profile).status,'RESOLVED')

    def test_conflicting_approved_variants_do_not_choose_a_value(self):
        profile={'_control_answer_bank':{'current ctc':dict(approved=True,answer='12 LPA'),
                                       'present salary':dict(approved=True,answer='13 LPA')}}
        self.assertNotEqual(resolve_application_answer('Current CTC (INR)',profile).status,'RESOLVED')

    def test_contact_wording_and_phone_format_preserve_verified_information(self):
        fields=(FormField('a','Please provide your email address',True,'email'),
                FormField('b','Mobile phone number',True,'tel'))
        self.assertEqual(build_fill_plan(fields,dict(email='fixture@example.invalid',phone='+91 (98765) 43210')).values,
                         dict(a='fixture@example.invalid',b='+919876543210'))

    def test_date_format_uses_explicit_dates_and_refuses_ambiguous_order(self):
        field=FormField('dob','Date of birth',True,'date')
        self.assertEqual(build_fill_plan((field,),dict(date_of_birth='31 January 1990')).values['dob'],'1990-01-31')
        self.assertTrue(build_fill_plan((field,),dict(date_of_birth='03/04/1990')).unknown_required_fields)

    def test_reviewed_control_variants_cannot_override_a_conflicting_private_fact(self):
        from sheet_control import ControlBundle,ControlSheetError,merge_control_profile
        bundle=ControlBundle({},(dict(question='present annual compensation in lpa',answer='13',approved=True,row=2),))
        with self.assertRaises(ControlSheetError):merge_control_profile(dict(current_ctc_inr='1250000'),bundle)

    def test_conflicting_duplicate_saved_answers_require_review(self):
        profile={'answers':{'do you hold a certificate':'Yes','Do you hold a certificate?':'No'}}
        answer=resolve_application_answer('Do you hold a certificate?',profile,options=('Yes','No'))
        self.assertNotEqual(answer.status,'RESOLVED')
        self.assertEqual(answer.reason,'conflicting_saved_answers')

    def test_existing_resume_extraction_supplies_only_missing_facts(self):
        from resume_facts import merge_verified_resume_facts
        from unittest.mock import patch
        with patch('resume_facts.derive_resume_facts',return_value={'customer_success_years':'7'}):
            merged=merge_verified_resume_facts({'email':'fixture@example.invalid'},'fixture.docx')
            self.assertEqual(resolve_application_answer('Customer success experience (years)',merged).answer,'7')
            self.assertEqual(merge_verified_resume_facts({'customer_success_years':'8'},'fixture.docx')['customer_success_years'],'8')


if __name__=='__main__':unittest.main()
