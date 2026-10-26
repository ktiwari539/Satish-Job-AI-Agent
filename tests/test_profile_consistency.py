import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from profile_consistency import verify_profile_consistency, ProfileFactsConflict


class ProfileConsistencyTests(unittest.TestCase):
    def facts(self,**updates):
        return dict(full_name='Fixture Applicant',email='fixture@example.invalid',phone='2025550123',**updates)

    def test_conflicting_total_experience_is_not_silently_overwritten(self):
        facts=self.facts(experience_years='7')
        with self.assertRaises(ProfileFactsConflict) as result:
            verify_profile_consistency(SimpleNamespace(total_experience_years=8),facts)
        self.assertEqual(result.exception.fields,('experience_years_conflicts_with_qualification_profile',))
        self.assertEqual(facts['experience_years'],'7')

    def test_lower_bound_experience_and_domain_experience_are_not_false_conflicts(self):
        verify_profile_consistency(SimpleNamespace(total_experience_years=8),self.facts(experience_years='7+',customer_success_years='6'))

    def test_search_location_is_not_confused_with_applicant_home_city(self):
        verify_profile_consistency(SimpleNamespace(total_experience_years=8,preferred_locations=['India']),self.facts(location='Fixture City',experience_years=8))

    def test_missing_identity_is_reported_without_logging_private_values(self):
        with self.assertRaises(ProfileFactsConflict) as result:
            verify_profile_consistency(SimpleNamespace(total_experience_years=8),{'full_name':'Fixture Applicant'})
        self.assertEqual(result.exception.fields,('email','phone'))
        self.assertNotIn('Fixture',str(result.exception))
