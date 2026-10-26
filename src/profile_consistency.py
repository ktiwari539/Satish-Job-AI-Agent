"""Cross-check declared applicant facts without inventing or overwriting them."""
import re
from decimal import Decimal


class ProfileFactsConflict(ValueError):
    def __init__(self, fields):
        super().__init__('applicant_facts_require_review')
        self.fields=tuple(fields)


def verify_profile_consistency(public_profile, private_profile):
    problems=[key for key in ('full_name','email','phone') if not str(private_profile.get(key) or '').strip()]
    total=Decimal(str(public_profile.total_experience_years))
    for key in ('experience_years','total_experience_years'):
        value=private_profile.get(key)
        if value in (None,''):
            continue
        text=str(value).strip()
        if not re.fullmatch(r'\d+(?:\.\d+)?\+?',text):
            problems.append(key+'_format_unverified')
            continue
        number=Decimal(text.rstrip('+'))
        conflict = total < number if text.endswith('+') else total != number
        if conflict:
            problems.append(key+'_conflicts_with_qualification_profile')
    if problems:
        raise ProfileFactsConflict(problems)
