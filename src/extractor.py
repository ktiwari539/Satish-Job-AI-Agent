import html
import re
from html.parser import HTMLParser
from typing import Iterable


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self.parts.append(data.strip())


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(html.unescape(value or ""))
    return " ".join(parser.parts)


def normalize_text(value: str) -> str:
    value = html_to_text(value).lower()
    value = re.sub(r"[^a-z0-9+#.\- ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_skills(description: str, taxonomy: Iterable[str]) -> tuple[str, ...]:
    text = normalize_text(description)
    found: list[str] = []
    for skill in taxonomy:
        normalized = normalize_text(skill)
        if not normalized:
            continue
        pattern = rf"(?<![a-z0-9+#]){re.escape(normalized)}(?![a-z0-9+#])"
        if re.search(pattern, text):
            found.append(skill.strip().lower())
    return tuple(sorted(set(found)))


def extract_minimum_years(description: str) -> int | None:
    text = normalize_text(description)
    patterns = (
        r"(?:minimum|min\.?|at least)\s+(\d{1,2})\+?\s+years?",
        r"(\d{1,2})\+\s+years?\s+(?:of\s+)?experience",
        r"(\d{1,2})\s+years?\s+(?:of\s+)?experience",
    )
    matches: list[int] = []
    for pattern in patterns:
        matches.extend(int(v) for v in re.findall(pattern, text))
    return min(matches) if matches else None


def detect_remote(title: str, location: str, description: str) -> bool:
    text = f" {normalize_text(' '.join((title, location, description)))} "
    return any(token in text for token in (" remote ", "work from home", "distributed team"))
