import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree


def _docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("word/document.xml")
    except Exception:
        return ""

    try:
        root = ElementTree.fromstring(raw)
    except Exception:
        return ""

    paragraphs = []
    for paragraph in root.iter():
        if paragraph.tag.endswith('}p'):
            paragraphs.append(' '.join(node.text for node in paragraph.iter()
                if node.tag.endswith('}t') and node.text))
    return '\n'.join(paragraphs)


def derive_resume_facts(resume_path: str) -> dict:
    """Derive only facts explicitly stated in the trusted local resume."""
    path = Path(resume_path)
    if path.suffix.lower() != ".docx":
        return {}

    text = _docx_text(path)
    if not text:
        return {}

    # Only complete positive statements or explicit labels establish tenure.
    # A title followed by overall career experience does not establish the
    # number of years in that role. Keep paragraph boundaries and '+' bounds.
    patterns = (
        r'customer success(?: management)? experience\s*[:=-]\s*(\d+(?:\.\d+)?)(\+)?\s+years?',
        r'(?:i have )?(\d+(?:\.\d+)?)(\+)?\s+years? (?:of |in )?customer success(?: management)?(?: experience)?',
        r'(?:i have )?(\d+(?:\.\d+)?)(\+)?\s+years? of experience in customer success(?: management)?',
    )
    quantities = set()
    # Periods inside decimal quantities are retained; sentences end at . + space.
    for clause in re.split(r'\n|;|\.(?=\s|$)',text.lower()):
        value = ' '.join(clause.split())
        for pattern in patterns:
            match = re.fullmatch(pattern,value)
            if match and 0 <= float(match[1]) <= 80:
                quantities.add(match[1]+(match[2] or ''))
    return {'customer_success_years':quantities.pop()} if len(quantities)==1 else {}


def merge_verified_resume_facts(profile, resume_path):
    """Use existing strict extraction for absent facts; preserve user decisions."""
    merged=dict(profile)
    for key,value in derive_resume_facts(resume_path).items():
        if merged.get(key) in (None,''):merged[key]=value
    return merged
