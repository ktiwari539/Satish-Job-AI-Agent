"""User-confirmed application exclusions that survive a fresh local database.

Issue #3 explicitly forbids retesting this manually submitted LinkedIn job.
Ordinary application dedupe remains in the local persistent ledger.
"""
CONFIRMED_LINKEDIN_JOB_IDS = frozenset({"4482859467"})


def is_confirmed_exclusion(source, external_id):
    return source == "linkedin" and str(external_id) in CONFIRMED_LINKEDIN_JOB_IDS
