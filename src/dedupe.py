import re
from hashlib import sha256

from extractor import normalize_text
from models import Job


COMPANY_SUFFIXES = (
    " private limited",
    " pvt ltd",
    " pvt. ltd.",
    " limited",
    " ltd",
    " llc",
    " inc",
    " corporation",
    " corp",
)

TITLE_MODIFIERS = {
    "senior", "sr", "junior", "jr", "principal", "staff",
    "associate", "lead", "level", "i", "ii", "iii",
}

DESCRIPTION_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "it", "of", "on", "or", "our", "that", "the", "their",
    "this", "to", "we", "will", "with", "you", "your",
}

LOCATION_ALIASES = {
    "bangalore": "bengaluru",
    "bombay": "mumbai",
    "gurgaon": "gurugram",
    "calcutta": "kolkata",
}

BROAD_LOCATION_TOKENS = {
    "india", "usa", "us", "uk", "united", "states", "kingdom",
}


def canonical_company(value: str) -> str:
    text = normalize_text(value)
    for suffix in COMPANY_SUFFIXES:
        normalized_suffix = normalize_text(suffix)
        if text.endswith(normalized_suffix):
            text = text[: -len(normalized_suffix)].strip()
    return re.sub(r"[^a-z0-9+#]+$", "", text).strip()


def canonical_title(value: str) -> str:
    text = normalize_text(value)
    text = re.sub(r"\b(remote|hybrid|onsite|on-site)\b", " ", text)
    text = re.sub(r"[^a-z0-9+#]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _title_tokens(value: str) -> tuple[str, ...]:
    tokens = tuple(
        token
        for token in canonical_title(value).split()
        if token and token not in TITLE_MODIFIERS
    )
    return tokens


def titles_similar(left: str, right: str) -> bool:
    """Return True only for a conservative same/similar-role match.

    Seniority modifiers are ignored, but role-head changes such as Manager to
    Director are not automatically collapsed. Generic one-token titles are not
    enough to establish similarity.
    """
    left_clean = canonical_title(left)
    right_clean = canonical_title(right)
    if not left_clean or not right_clean:
        return False
    if left_clean == right_clean:
        return True

    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    if left_tokens == right_tokens:
        return True

    left_set = set(left_tokens)
    right_set = set(right_tokens)
    smaller = left_set if len(left_set) <= len(right_set) else right_set
    larger = right_set if smaller is left_set else left_set
    intersection = left_set & right_set

    # "Support Manager" and "Customer Support Manager" are the same role
    # family, but a generic one-token overlap such as "Manager" is insufficient.
    if len(smaller) >= 2 and smaller.issubset(larger):
        return True

    union = left_set | right_set
    similarity = len(intersection) / len(union) if union else 0.0
    return len(intersection) >= 2 and similarity >= 0.67


def _description_tokens(value: str) -> tuple[str, ...]:
    raw = re.findall(r"[a-z0-9+#]+", normalize_text(value))
    return tuple(
        token
        for token in raw
        if len(token) > 1 and token not in DESCRIPTION_STOP_WORDS
    )


def _shingles(tokens: tuple[str, ...], size: int = 3) -> set[tuple[str, ...]]:
    if len(tokens) < size:
        return set()
    return {
        tuple(tokens[index:index + size])
        for index in range(0, len(tokens) - size + 1)
    }


def material_job_description_change(
    previous: str,
    current: str,
    *,
    minimum_tokens: int = 40,
) -> bool:
    """Return True only when two sufficiently complete JDs materially differ.

    Missing/short descriptions never create an exception to the cooldown. That
    keeps dedupe fail-closed when there is not enough evidence to prove the role
    changed.
    """
    previous_tokens = _description_tokens(previous)
    current_tokens = _description_tokens(current)
    if len(previous_tokens) < minimum_tokens or len(current_tokens) < minimum_tokens:
        return False

    previous_set = set(previous_tokens)
    current_set = set(current_tokens)
    token_union = previous_set | current_set
    token_similarity = (
        len(previous_set & current_set) / len(token_union)
        if token_union else 1.0
    )

    previous_shingles = _shingles(previous_tokens)
    current_shingles = _shingles(current_tokens)
    shingle_union = previous_shingles | current_shingles
    shingle_similarity = (
        len(previous_shingles & current_shingles) / len(shingle_union)
        if shingle_union else 1.0
    )

    return token_similarity < 0.60 and shingle_similarity < 0.35


def _location_tokens(value: str) -> set[str]:
    raw = re.findall(r"[a-z0-9]+", normalize_text(value))
    tokens = [LOCATION_ALIASES.get(token, token) for token in raw if token]
    if len(tokens) > 1:
        specific = [token for token in tokens if token not in BROAD_LOCATION_TOKENS]
        if specific:
            tokens = specific
    return set(tokens)


def material_location_change(previous: str, current: str) -> bool:
    """Treat a location as materially changed only with clear different evidence.

    Formatting additions such as country/state names do not count by themselves.
    Distinct cities or remote-vs-city locations do.
    """
    previous_tokens = _location_tokens(previous)
    current_tokens = _location_tokens(current)
    if not previous_tokens or not current_tokens:
        return False
    if previous_tokens == current_tokens:
        return False
    return not bool(previous_tokens & current_tokens)


def canonical_job_fingerprint(job: Job) -> str:
    company = canonical_company(job.company)
    title = canonical_title(job.title)
    location = normalize_text(job.location)
    payload = f"{company}|{title}|{location}"
    return sha256(payload.encode("utf-8")).hexdigest()
