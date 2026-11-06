"""Bounded search classification, identity validation and diagnostic privacy."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from linkedin_discovery import decode_probe,discovery_status,discover_search,route_state,main

SEARCH='https://www.linkedin.com/jobs/search/?keywords=Customer+Success+Manager'
ID='9300000001'


def payload(rows=None,**signals):
    return dict(rows=[] if rows is None else rows,signals=dict(ready_complete=True,**signals))


def row(**changes):
    return dict(dict(title='Customer Success Manager',company='Fixture Employer',location='India',
                     hrefs=['https://www.linkedin.com/jobs/view/'+ID+'/'],ids=[ID]),**changes)


class Page:
    def __init__(self,data,url=SEARCH):self.data=data;self.url=url;self.probes=0;self.waits=[]
    def is_closed(self):return False
    def evaluate(self,*_):self.probes+=1;return self.data
    def wait_for_timeout(self,value):self.waits.append(value)


class LinkedInDiscoveryTests(unittest.TestCase):
    def test_observed_id_produces_only_its_canonical_job_identity(self):
        cards,evidence=decode_probe(payload([row(hrefs=['https://www.linkedin.com/jobs/view/customer-success-manager-at-fixture-'+ID+'/?tracking=private'])]))
        self.assertEqual(len(cards),1)
        self.assertEqual((cards[0].external_id,cards[0].url),(ID,'https://www.linkedin.com/jobs/view/'+ID+'/'))
        self.assertNotIn('tracking',json.dumps(evidence))

    def test_conflicting_root_href_duplicate_or_untrusted_id_is_not_a_job(self):
        for item in (row(ids=['9300000002']),row(hrefs=['https://www.linkedin.com/jobs/view/'+ID+'/?currentJobId=9300000002']),
                     row(hrefs=['https://evil.invalid/jobs/view/'+ID+'/']),row(ids=['not-a-posting'])):
            self.assertEqual(decode_probe(payload([item]))[0],[])
        cards,evidence=decode_probe(payload([row(),row(title='Different job title')]))
        self.assertEqual(cards,[]);self.assertGreater(evidence['identity_conflicts'],0)

    def test_missing_company_or_location_remains_unresolved_metadata(self):
        cards,evidence=decode_probe(payload([row(company='',location='')]))
        self.assertEqual(len(cards),1)
        self.assertEqual((cards[0].company,cards[0].location),('',''))
        self.assertEqual(evidence['metadata_pending'],1)

    def test_duplicates_with_consistent_identity_use_complete_scoped_metadata(self):
        cards,evidence=decode_probe(payload([row(company='',location=''),row()]))
        self.assertEqual(len(cards),1);self.assertEqual(cards[0].company,'Fixture Employer')
        self.assertEqual(evidence['duplicate_cards'],1)

    def test_auth_challenge_and_explicit_no_results_take_precedence_over_stale_cards(self):
        for flag,status in (('login','SEARCH_LOGIN_REQUIRED'),('challenge','SEARCH_CHALLENGE'),
                           ('no_results','SEARCH_NO_RESULTS'),('page_error','SEARCH_PAGE_ERROR')):
            result=discover_search(Page(payload([row()],**{flag:True})),(),timeout_ms=0)
            self.assertEqual(result.status,status);self.assertEqual(result.jobs,())

    def test_loading_results_do_not_release_stale_cards(self):
        result=discover_search(Page(payload([row()],results_busy=True)),(),timeout_ms=0)
        self.assertEqual(result.status,'SEARCH_LOADING_TIMEOUT');self.assertEqual(result.jobs,())

    def test_origin_route_and_keyword_change_are_classified_without_dom_reads(self):
        cases=[('https://www.linkedin.com/login?return=private','SEARCH_LOGIN_REQUIRED'),
               ('https://www.linkedin.com/checkpoint/challenge/private','SEARCH_CHALLENGE'),
               ('https://www.linkedin.com/jobs/search/?keywords=unrelated','SEARCH_CONTEXT_MISMATCH'),
               ('https://linkedin.com.evil.invalid/jobs/search/','SEARCH_ROUTE_MISMATCH')]
        for url,status in cases:
            page=Page(payload([row()]),url)
            result=discover_search(page,(),expected_query='Customer Success Manager',timeout_ms=0)
            self.assertEqual((result.status,page.probes),(status,0))
            self.assertNotIn('private',json.dumps(result.evidence))

    def test_all_empty_cases_have_bounded_wait_and_specific_evidence(self):
        for data,status in ((payload(loading=True),'SEARCH_LOADING_TIMEOUT'),
                            (payload(candidate_cards=1),'SEARCH_CARD_METADATA_INCOMPLETE'),
                            (payload(),'SEARCH_MARKUP_UNSUPPORTED'),(None,'SEARCH_PROBE_UNAVAILABLE')):
            page=Page(data)
            result=discover_search(page,(),timeout_ms=10,poll_ms=5)
            self.assertEqual(result.status,status)
            self.assertLessEqual(page.probes,4);self.assertLessEqual(len(page.waits),3)

    def test_navigation_during_probe_discards_previous_cards(self):
        page=Page(payload([row()]))
        def redirect(*_):
            page.url='https://www.linkedin.com/login'
            return payload([row()])
        page.evaluate=redirect
        result=discover_search(page,(),expected_query='Customer Success Manager',timeout_ms=0)
        self.assertEqual(result.status,'SEARCH_LOGIN_REQUIRED')
        self.assertEqual(result.jobs,())

    def test_diagnostics_reject_page_strings_extra_fields_and_non_boolean_values(self):
        data=payload([row()]);data['signals'].update(body_chars='private@example.invalid',password='secret',login='yes',html='<private>')
        _,evidence=decode_probe(data)
        self.assertEqual(evidence['body_chars'],0);self.assertFalse(evidence['login'])
        encoded=json.dumps(evidence)
        for value in ('private@example.invalid','secret','<private>','Fixture Employer',ID):self.assertNotIn(value,encoded)

    def test_read_only_command_refuses_overlapping_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'search.json';page=Page(payload(no_results=True))
            runtime=MagicMock();runtime.__enter__.return_value.page=page
            args=['linkedin_discovery.py','--report',str(path)]
            with patch.object(sys,'argv',args),patch('browser_runtime.PlaywrightSession',return_value=runtime), \
                 patch('browser_portals.LinkedInBrowserAdapter.open_search') as search, \
                 patch('resume_store.resolve_current_resume',side_effect=AssertionError('must not read resume')), \
                 patch('auth_bridge.AuthProvider',side_effect=AssertionError('must not request credentials')), \
                 patch('scheduled_review.acquire_run_lock',return_value=None),redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(),4)
                self.assertEqual(json.loads(output.getvalue())['status'],'review_worker_already_running')
                search.assert_not_called()

    def test_read_only_command_writes_shareable_evidence_without_applicant_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'search.json';page=Page(payload(no_results=True))
            runtime=MagicMock();runtime.__enter__.return_value.page=page
            descriptor=os.open(Path(folder)/'lock',os.O_CREAT|os.O_RDWR,0o600)
            with patch.object(sys,'argv',['linkedin_discovery.py','--report',str(path)]), \
                 patch('browser_runtime.PlaywrightSession',return_value=runtime), \
                 patch('browser_portals.LinkedInBrowserAdapter.open_search'), \
                 patch('resume_store.resolve_current_resume',side_effect=AssertionError('must not read resume')), \
                 patch('auth_bridge.AuthProvider',side_effect=AssertionError('must not request credentials')), \
                 patch('scheduled_review.acquire_run_lock',return_value=descriptor),redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(),4)
            self.assertEqual(json.loads(path.read_text())['status'],'SEARCH_NO_RESULTS')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertFalse(json.loads(output.getvalue())['application_form_exercised'])




if __name__=='__main__':unittest.main()
