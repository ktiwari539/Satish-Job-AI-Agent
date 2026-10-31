"""Shared non-submitting release checks; Review is not submission approval."""


def review_identity_verified(profile, checks):
    return all(
        str(profile.get(key) or "").strip() and key + ":matched" in checks
        for key in ("full_name", "email", "phone")
    )
