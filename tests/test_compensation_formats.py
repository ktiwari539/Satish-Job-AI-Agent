"""Verified salary facts must reach numeric inputs in the requested scale."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from answer_facts import fact_question,format_field_answer,quantity
from application_forms import FormField,build_fill_plan


class CompensationFormats(unittest.TestCase):
    def test_compensation_notation_cannot_change_other_fact_units(self):
        for value,key in (('annual 7 years','experience_years'),('INR 7 years','experience_years'),('30 days per annum','notice_period_days')):
            self.assertIsNone(quantity(value,key,source_unit='years' if key=='experience_years' else 'days'))

    def test_annual_rupees_default_for_current_and_expected_wording(self):
        profile=dict(current_ctc='13.4 LPA',expected_ctc='21.75 LPA')
        for current in ('What is your current annual compensation?','Current CTC','Present yearly salary (numbers only)','Your last drawn annual CTC'):
            for expected in ('Annual compensation expectation','What are your salary expectations?','What is your expected CTC?','Desired annual pay in INR'):
                with self.subTest(current=current,expected=expected):
                    fields=(FormField('a',current,True),FormField('b',expected,True,'number'))
                    plan=build_fill_plan(fields,profile)
                    self.assertEqual(plan.values,{'a':'1340000','b':'2175000'})
                    self.assertFalse(plan.unknown_required_fields)
        self.assertEqual(profile,dict(current_ctc='13.4 LPA',expected_ctc='21.75 LPA'))

    def test_exact_and_variant_control_answers_reach_the_same_numeric_values(self):
        fields=(FormField('a','Current annual compensation',True),FormField('b','Expected annual compensation',True,'number'))
        for bank in (
            {'current annual compensation':dict(approved=True,answer='13.4 LPA'),'expected annual compensation':dict(approved=True,answer='21.75 LPA')},
            {'current ctc in lpa':dict(approved=True,answer='13.4'),'expected ctc in lpa':dict(approved=True,answer='21.75')},
        ):
            self.assertEqual(build_fill_plan(fields,{'_control_answer_bank':bank}).values,{'a':'1340000','b':'2175000'})

    def test_job_answer_and_canonical_facts_use_visible_lpa_scale(self):
        fields=(FormField('currentSalary.amount','Current CTC (INR in LPA)',True,'number'),FormField('expectedSalary.amount','Expected CTC (INR)',True))
        profiles=(dict(current_ctc_inr='1340000',expected_ctc_inr='2175000'),
            {'_application_job':'linkedin:9600000001','job_answers':{'linkedin:9600000001':{'Current CTC (INR in LPA)':'INR 13,40,000','Expected CTC (INR)':'21.75 LPA'}}})
        for profile in profiles:
            self.assertEqual(build_fill_plan(fields,profile).values,{'currentSalary.amount':'13.4','expectedSalary.amount':'2175000'})

    def test_indian_and_western_grouped_amounts_are_plain_digits(self):
        for value in ('INR 13,40,000','Rs. 1,340,000','1340000 INR','13.4 lakhs per annum','13.4 LPA annual'):
            with self.subTest(value=value):
                self.assertEqual(format_field_answer('Current annual compensation',value,'text'),'1340000')
        self.assertIsNone(format_field_answer('Current CTC','13,4,000','number'))
        self.assertIsNone(format_field_answer('Current CTC','1,2','text'))

    def test_foreign_monthly_component_and_mixed_scope_do_not_borrow_inr_fact(self):
        for prompt in ('Current CTC (USD)','Expected monthly compensation','Current fixed annual compensation','Current and expected salary','Annual compensation'):
            with self.subTest(prompt=prompt):self.assertIsNone(fact_question(prompt))
        for value in ('USD 1340000','1340000 monthly','13.4-15 LPA','13.4+ LPA','negotiable','NaN','-1'):
            self.assertIsNone(format_field_answer('Current CTC',value,'text'))

    def test_bare_approved_lpa_number_keeps_its_requested_scale(self):
        for question,answer in (('Current CTC (LPA)','13.4'),('Current CTC','1340000')):
            self.assertEqual(format_field_answer(question,answer,'number'),answer)
        self.assertEqual(format_field_answer('Current CTC (LPA)','1340000 INR','number'),'13.4')

    def test_unapproved_salary_scope_still_blocks_numeric_fact(self):
        profile=dict(current_ctc_inr='1340000',_control_answer_bank={'current ctc':dict(approved=False,answer='13.4 LPA')})
        plan=build_fill_plan((FormField('a','Present annual compensation',True),),profile)
        self.assertFalse(plan.values);self.assertTrue(plan.unknown_required_fields)

    def test_conflicting_canonical_and_legacy_salary_facts_require_review(self):
        profile=dict(current_ctc='13.4 LPA',current_ctc_inr='1700000')
        for question in ('What is your current CTC?','Current annual compensation (INR)','Current CTC (LPA)'):
            self.assertFalse(build_fill_plan((FormField('a',question,True),),profile).values)

    def test_exact_dropdown_label_remains_an_observed_option(self):
        field=FormField('a','Current annual CTC in LPA',True,'select-one',('Choose','13.4 LPA','21.75 LPA'))
        self.assertEqual(build_fill_plan((field,),dict(current_ctc_inr='1340000')).values,{'a':'13.4 LPA'})
