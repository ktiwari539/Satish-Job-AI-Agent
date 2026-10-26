"""Privacy-preserving read-only evidence for the selected application resume.

Never logs a filename, DOM text, local path, or resume contents. A selected
local file input is not proof that LinkedIn accepted the attachment.
"""
import json
from pathlib import Path


def _expected_names(resume_path: str) -> list[str]:
    target = Path(resume_path).expanduser()
    names = [target.name]
    manifest = target.parent / "manifest.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if payload.get("current_file") == target.name:
            original = str(payload.get("original_name") or "").strip()
            if original:
                names.append(Path(original).name)
    except (OSError, ValueError, TypeError):
        pass
    return list(dict.fromkeys(name.lower().strip() for name in names if name))


_RESUME_PROBE = r"""({ names }) => {
  const canonical = v => String(v || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const expected = names.map(canonical).filter(Boolean);
  const visible = el => {
    if (!el || !el.isConnected) return false;
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' &&
           r.width > 0 && r.height > 0;
  };
  const roots = Array.from(document.querySelectorAll(
    '.jobs-easy-apply-modal, .artdeco-modal, [role="dialog"]'
  )).filter(visible);
  // An inline application wizard can have no dialog. Use a bounded,
  // application-related container, not arbitrary saved-profile text.
  const inline = Array.from(document.querySelectorAll(
    '.jobs-easy-apply-content, .jobs-easy-apply-form-section__grouping, ' +
    '[class*="jobs-easy-apply"], [data-test*="resume"]'
  )).filter(visible);
  // Some LinkedIn Easy Apply pages are inline and have no known
  // jobs-easy-apply classes. Limit fallback to a visible N/M pages counter,
  // bounded ancestor, real editable fields, and a Next/Review control.
  // This is NOT permission to consider any filename in document.body proof.
  const pageCounters = Array.from(document.querySelectorAll(
    'span, p, small, div'
  )).filter(visible).filter(el => {
    const t = canonical(el.innerText || el.textContent);
    return /^\d+\s*\/\s*\d+\s*pages?$/.test(t) &&
      !Array.from(el.children || []).some(child =>
        /^\d+\s*\/\s*\d+\s*pages?$/.test(
          canonical(child.innerText || child.textContent)));
  });
  let inlineWizard = null;
  for (const marker of pageCounters.slice(0, 12)) {
    let candidate = marker.parentElement;
    for (let depth = 0; candidate && depth < 10;
         depth++, candidate = candidate.parentElement) {
      if (!visible(candidate)) continue;
      const text = canonical(candidate.innerText || candidate.textContent);
      if (text.length > 9000) break;
      if (!candidate.querySelector('input, textarea, select')) continue;
      const hasNext = Array.from(candidate.querySelectorAll(
        'button, [role="button"]'
      )).some(button => visible(button) &&
        /^(next|review|back|continue)$/i.test(
          canonical(button.innerText || button.textContent ||
                    button.getAttribute('aria-label'))));
      if (hasNext) {
        if (!inlineWizard ||
            text.length < canonical(inlineWizard.innerText).length)
          inlineWizard = candidate;
        break;
      }
    }
  }
  const scoped = roots.length ? roots : inline;
  const containers = Array.from(new Set([
    ...scoped, ...(inlineWizard ? [inlineWizard] : [])
  ]));
  let localFileSelected = false, savedMatch = false, savedMismatch = false;
  for (const root of containers) {
    for (const input of root.querySelectorAll('input[type="file"]')) {
      for (const file of Array.from(input.files || [])) {
        if (expected.includes(canonical(file.name))) localFileSelected = true;
      }
    }
    const selected = root.querySelectorAll(
      'input[type="radio"]:checked, [role="radio"][aria-checked="true"], ' +
      '[aria-selected="true"]'
    );
    for (const node of selected) {
      let candidate = '';
      if (node.id) {
        const label = root.querySelector('label[for="' + CSS.escape(node.id) + '"]');
        if (label) candidate += ' ' + (label.innerText || label.textContent || '');
      }
      const box = node.closest('label, [class*="resume"], [class*="document"]');
      if (box && visible(box)) candidate += ' ' + (box.innerText || box.textContent || '');
      // LinkedIn's inline saved-resume cards may have a native radio with
      // no wrapping label/resume class. Inspect only three bounded ancestors
      // inside the verified application wizard, never the whole page.
      if (!/\\.(pdf|docx?)\\b/i.test(candidate)) {
        let parent = node.parentElement;
        for (let depth = 0; parent && depth < 3 && root.contains(parent);
             depth++, parent = parent.parentElement) {
          if (!visible(parent)) continue;
          const text = canonical(parent.innerText || parent.textContent);
          if (text.length > 350) break;
          if (/\\.(pdf|docx?)\\b/i.test(text)) {
            candidate += ' ' + text;
            break;
          }
        }
      }
      candidate = canonical(candidate).slice(0, 300);
      if (!/\.(pdf|docx?)\b/i.test(candidate)) continue;
      if (expected.some(name => candidate.includes(name))) savedMatch = true;
      else savedMismatch = true;
    }
  }
  return {savedMatch, savedMismatch, localFileSelected};
}"""


def inspect_resume_evidence(page, resume_path: str) -> str:
    """Return a safe categorical state, never the actual file name."""
    if not resume_path:
        return "no_resume_configured"
    try:
        raw = page.evaluate(_RESUME_PROBE, {"names": _expected_names(resume_path)})
    except Exception:
        return "attachment_unverified"
    if not isinstance(raw, dict):
        return "attachment_unverified"
    if raw.get("savedMismatch") is True:
        return "different_resume_selected"
    if raw.get("savedMatch") is True:
        return "matching_resume_selected"
    if raw.get("localFileSelected") is True:
        return "file_input_selected_unconfirmed"
    return "attachment_unverified"
