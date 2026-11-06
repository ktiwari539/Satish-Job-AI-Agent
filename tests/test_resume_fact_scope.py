"""Explicit role tenure only; overall career years are not role-specific facts."""
from pathlib import Path
import sys
import tempfile
import unittest
from xml.sax.saxutils import escape
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from resume_facts import derive_resume_facts


class ResumeFactScopeTests(unittest.TestCase):
    def derive(self,*paragraphs):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'synthetic.docx'
            with ZipFile(path,'w') as archive:
                archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+''.join('<w:p><w:r><w:t>'+escape(text)+'</w:t></w:r></w:p>' for text in paragraphs)+'</w:body></w:document>')
            return derive_resume_facts(str(path))

    def test_leadership_summary_overall_years_are_not_customer_success_tenure(self):
        self.assertEqual(self.derive('Strategic Customer Success Leader with 9+ years of progressive professional experience.'),{})
        self.assertEqual(self.derive('Customer Success Manager','Total professional experience: 9 years'),{})

    def test_explicit_positive_role_duration_can_be_used(self):
        for statement in ('Customer success experience: 3 years','I have 3 years of customer success experience.',
                          '3 years of experience in customer success'):
            self.assertEqual(self.derive(statement),{'customer_success_years':'3'})

    def test_lower_bounds_decimals_and_paragraph_scope_are_preserved(self):
        self.assertEqual(self.derive('Customer success experience: 3+ years'),{'customer_success_years':'3+'})
        self.assertEqual(self.derive('Customer success experience: 3.5 years'),{'customer_success_years':'3.5'})
        self.assertEqual(self.derive('Customer Success','3 years of support experience'),{})

    def test_negative_compound_and_conflicting_statements_remain_unknown(self):
        for statement in ('I do not have 3 years of customer success experience',
                          '3 years of customer success and technical support experience',
                          'Customer success experience required: 3 years',
                          'Minimum 3 years of customer success experience'):
            self.assertEqual(self.derive(statement),{})
        self.assertEqual(self.derive('Customer success experience: 3 years','Customer success experience: 5 years'),{})


if __name__=='__main__': unittest.main()
