import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from browser_extractors import canonicalize_job_url, normalize_browser_card, RawJobCard
from portal_preparation import valid_portal_job_url
from models import Job


class CrossPortalIdentityTests(unittest.TestCase):
    def test_indeed_job_keys_are_not_removed_as_tracking(self):
        a=canonicalize_job_url('https://in.indeed.com/viewjob?jk=abc123&from=search#top')
        b=canonicalize_job_url('https://in.indeed.com/viewjob?jk=def456&from=search')
        self.assertEqual(a, 'https://in.indeed.com/viewjob?jk=abc123')
        self.assertNotEqual(a,b)

    def test_indeed_click_and_detail_links_resolve_to_the_same_job(self):
        a=canonicalize_job_url('https://in.indeed.com/rc/clk?jk=abc123&from=search')
        b=canonicalize_job_url('https://in.indeed.com/jobs?vjk=abc123&q=role')
        self.assertEqual(a,b)

    def test_ambiguous_indeed_identity_is_not_collapsed_or_accepted(self):
        url='https://in.indeed.com/viewjob?jk=abc123&jk=def456'
        self.assertEqual(parse_qs(urlsplit(canonicalize_job_url(url)).query)['jk'], ['abc123','def456'])
        job=Job('indeed','abc123','Fixture','Role','India',url,'description')
        self.assertFalse(valid_portal_job_url(job))

    def test_other_ats_identity_parameters_survive_tracking_removal(self):
        self.assertEqual(canonicalize_job_url('https://example.invalid/careers?gh_jid=123&utm_source=x'),
                         'https://example.invalid/careers?gh_jid=123')

    def test_known_portal_ids_are_extracted_without_nested_data_attributes(self):
        linkedin=normalize_browser_card('linkedin',RawJobCard('Role','Fixture','India','https://www.linkedin.com/jobs/view/9000000001/'),())
        indeed=normalize_browser_card('indeed',RawJobCard('Role','Fixture','India','https://in.indeed.com/viewjob?jk=abc123'),())
        self.assertEqual(linkedin.external_id,'9000000001')
        self.assertEqual(indeed.external_id,'abc123')

    def test_profile_pages_and_wrong_job_ids_are_not_application_pages(self):
        cases=[('naukri','1','https://www.naukri.com/mnjuser/profile'),
               ('indeed','abc123','https://in.indeed.com/login?jk=abc123'),
               ('greenhouse','123','https://boards.greenhouse.io/fixture/jobs/456'),
               ('lever','123','https://jobs.lever.co/fixture/456')]
        for portal,jid,url in cases:
            self.assertFalse(valid_portal_job_url(Job(portal,jid,'Fixture','Role','India',url,'')))
