import sys
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import MagicMock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from models import Job
from verified_jd import read_verified_job_description
from test_linkedin_exact_page_layouts import Page,TextElement,LONG_JD
from jd_enrichment import _read_first_visible


class VerifiedJDTests(unittest.TestCase):
    def setUp(self):
        self.job=Job('linkedin','4476701830','Example Employer','Customer Success Manager','India',
                     'https://www.linkedin.com/jobs/view/4476701830/','')
        self.page=MagicMock(); self.page.url=self.job.url; self.page.is_closed.return_value=False

    def read(self,**kwargs):
        return read_verified_job_description(self.page,self.job,('customer success',),max_probes=2,**kwargs)

    def test_short_placeholder_never_starves_longer_visible_description(self):
        page=Page({'.short':[TextElement('About the job')],'.full':[TextElement(LONG_JD)]})
        self.assertEqual(_read_first_visible(page,('.short','.full'),min_chars=120),LONG_JD.strip())

    def test_delayed_hydration_is_retried_without_reading_the_whole_body(self):
        with patch('verified_jd._read_first_visible',side_effect=['',LONG_JD]),patch('verified_jd._structured_details',return_value=None):
            result,evidence=self.read()
        self.assertTrue(result.enriched); self.assertEqual(evidence['probes'],2)
        self.page.wait_for_timeout.assert_called_once_with(400)
        self.assertEqual(evidence['read_route'],'visible_scoped')

    def test_exact_id_structured_description_is_reused(self):
        with patch('verified_jd._read_first_visible',return_value=''),patch('verified_jd._structured_details',return_value=('Customer Success Manager','Example Employer','India',LONG_JD)):
            result,evidence=self.read()
        self.assertTrue(result.enriched); self.assertEqual(evidence['read_route'],'exact_job_structured')

    def test_checkpoint_never_fetches_a_public_page_to_hide_auth_failure(self):
        with patch('verified_jd._safe_page_state',return_value={'page_state':'security_checkpoint'}),patch('verified_jd.fetch_public_exact_linkedin_job') as fetch:
            result,evidence=self.read(allow_public_fallback=True)
        fetch.assert_not_called(); self.assertEqual(result.reason,'jd_security_challenge')

    def test_missing_layout_has_structural_evidence_without_any_job_text(self):
        with patch('verified_jd._read_first_visible',return_value=''),patch('verified_jd._structured_details',return_value=None):
            result,evidence=self.read()
        self.assertEqual(result.reason,'jd_missing_selector_layout')
        self.assertIn('selectors',evidence); self.assertNotIn(LONG_JD,str(evidence))

    def test_public_fallback_must_match_card_company_and_role(self):
        with patch('verified_jd._read_first_visible',return_value=''),patch('verified_jd._structured_details',return_value=None),patch('verified_jd.fetch_public_exact_linkedin_job',return_value=replace(self.job,company='Other Employer',description=LONG_JD)):
            result,evidence=self.read(allow_public_fallback=True)
        self.assertFalse(result.enriched); self.assertEqual(result.reason,'jd_listing_metadata_conflict')

    def test_navigation_to_another_job_is_not_an_enrichment(self):
        self.page.url='https://www.linkedin.com/jobs/view/4476701831/'
        with patch('verified_jd._read_first_visible') as read:
            result,evidence=self.read(allow_public_fallback=True)
        read.assert_not_called(); self.assertEqual(result.reason,'jd_job_identity_mismatch')

    def test_elapsed_deadline_stops_before_all_remaining_hydration_retries(self):
        with patch('verified_jd._read_first_visible',return_value='') as read, \
             patch('verified_jd._structured_details',return_value=None), \
             patch('verified_jd.time.monotonic',side_effect=[0,9]):
            result,evidence=read_verified_job_description(self.page,self.job,(),max_probes=21)
        self.assertFalse(result.enriched); self.assertEqual(evidence['probes'],1)
        read.assert_called_once(); self.page.wait_for_timeout.assert_not_called()
