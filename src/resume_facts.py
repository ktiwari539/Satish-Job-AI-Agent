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

    parts = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            parts.append(node.text)
    return " ".join(parts)


def derive_resume_facts(resume_path: str) -> dict:
    """Derive only facts explicitly stated in the trusted local resume."""
    path = Path(resume_path)
    if path.suffix.lower() != ".docx":
        return {}

    text = " ".join(_docx_text(path).split())
    if not text:
        return {}

    lowered = text.lower()
    facts = {}

    # Example: "Strategic Customer Success Leader with 7+ years ..."
    patterns = (
        r"customer success.{0,80}?with\s+(\d+(?:\.\d+)?)\+?\s+years",
        r"customer success.{0,120}?(\d+(?:\.\d+)?)\+?\s+years",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            facts["customer_success_years"] = match.group(1)
            break

    return facts
