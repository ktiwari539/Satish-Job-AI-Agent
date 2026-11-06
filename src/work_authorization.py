"""Narrow jurisdiction-specific questions that one verified boolean can answer."""
import re


def is_india_authorization_question(question):
    text = ' '.join(re.sub(r'[^a-z0-9]+', ' ', str(question or '').lower()).split())
    patterns = (
        r'work authori[sz]ation in india',
        r'are you (?:legally )?(?:authori[sz]ed|eligible|allowed) to work in india',
        r'do you have (?:the )?(?:legal )?(?:right|authori[sz]ation) to work in india',
        r'can you legally work in india',
    )
    # Full matching excludes sponsorship, permanence, citizenship, negation,
    # another country, or any second assertion bundled into the question.
    return any(re.fullmatch(pattern, text) for pattern in patterns)
